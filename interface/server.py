"""Local UI + single-worker Python/Motor-CAD execution. No AI service required."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import subprocess
import sys
import threading
import time
import re
from urllib.parse import urlparse,parse_qs

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'validation'))
from design_job import validate,write_json
from motorcad_open import queue_open
from formula_job import validate_formula
from verify_formula_job import verification_estimate
from rotor_catalog import catalog_payload,preflight
from topology_study import run_study
from model_capabilities import check_model_support
from task_store import TaskStore,import_checklist
from task_queue import create_plan,launch as launch_task_queue,worker_active as task_worker_active
from verification_scope import current_checklist_path
from spm_geometry import preview as spm_geometry_preview
from detailed_spm_recipe import compile_recipe as compile_detailed_spm_recipe
from result_review import review_result
import breadloaf_gui
JOBS=ROOT/'validation/jobs';JOBS.mkdir(exist_ok=True)
lock=threading.Lock();active=None;active_job=None

def launch_worker(request,script):
    global active,active_job
    with lock:
        if active and active.poll() is None:raise ValueError('A calculation is already running')
        job=time.strftime('%Y%m%d_%H%M%S');folder=JOBS/job
        if folder.exists():job+='_'+str(time.time_ns()%1000000);folder=JOBS/job
        folder.mkdir();write_json(folder/'request.json',request);write_json(folder/'progress.json',{'status':'queued','started_unix':time.time()})
        with (folder/'worker.log').open('ab') as log:
            active=subprocess.Popen([sys.executable,str(ROOT/'validation'/script),'--job',str(folder)],cwd=str(ROOT),
                stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        active_job=job
    return job

def saved_formula(data):
    job=data.get('id','')
    if not re.fullmatch(r'\d{8}_\d{6}(?:_\d+)?',job):raise ValueError('Invalid formula job ID')
    formula=json.loads((JOBS/job/'result.json').read_text(encoding='utf-8'))
    if formula.get('stage')!='formula':raise ValueError('Select a completed formula optimization')
    ids=data.get('selected_model_ids',[])
    if not isinstance(ids,list) or not ids or any(not isinstance(v,str) for v in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Select one or more distinct saved models')
    verification_estimate(formula,ids)
    return job,formula,ids

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'interface'),**kwargs)
    def reply(self,status,data):
        raw=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        path=urlparse(self.path)
        if path.path=='/api/rotor-catalog':return self.reply(200,catalog_payload())
        if path.path=='/api/breadloaf':
            try:
                job=parse_qs(path.query).get('id',[None])[0]
                return self.reply(200,breadloaf_gui.detail(job) if job else breadloaf_gui.jobs())
            except (ValueError,KeyError,FileNotFoundError) as exc:return self.reply(400,{'error':str(exc)})
        if path.path=='/api/result-review':
            job=parse_qs(path.query).get('id',[''])[0]
            if not re.fullmatch(r'\d{8}_\d{6}(?:_\d+)?',job):return self.reply(400,{'error':'Invalid job ID'})
            try:
                result=json.loads((JOBS/job/'result.json').read_text(encoding='utf-8'))
                return self.reply(200,review_result(result,JOBS/job))
            except (ValueError,KeyError,FileNotFoundError) as exc:return self.reply(400,{'error':str(exc)})
        if path.path=='/api/task-queue':
            try:
                store=TaskStore();job=parse_qs(path.query).get('id',[None])[0]
                return self.reply(200,{**(store.snapshot(job) if job else {'jobs':store.list_jobs()}),
                                       'worker_active':task_worker_active(store)})
            except ValueError as exc:return self.reply(400,{'error':str(exc)})
        if path.path=='/api/task-queue/artifact':
            try:
                query=parse_qs(path.query)
                job=query.get('job',[''])[0];task=query.get('task',[''])[0]
                attempt=int(query.get('attempt',['0'])[0]);name=query.get('file',[''])[0]
                file=TaskStore().artifact(job,task,attempt,name);raw=file.read_bytes()
                self.send_response(200);self.send_header('Cache-Control','no-store')
                self.send_header('Content-Type','application/json; charset=utf-8' if file.suffix=='.json' else 'text/plain; charset=utf-8')
                self.send_header('Content-Disposition',f'attachment; filename="{name}"')
                self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            except (ValueError,FileNotFoundError) as exc:return self.reply(404,{'error':str(exc)})
        if path.path=='/api/health':return self.reply(200,{'ok':True,'engine':'local Python / PyMotorCAD','scope':'SPM 4-pole / 12-slot / delta / ID0 or MTPA + optional field weakening / SVPWM / 50PN470 N48UH'})
        if path.path=='/api/job':
            job=parse_qs(path.query).get('id',[''])[0]
            if not re.fullmatch(r'\d{8}_\d{6}(?:_\d+)?',job):return self.reply(400,{'error':'Invalid job ID'})
            folder=JOBS/job
            if not folder.exists():return self.reply(404,{'error':'Job not found'})
            progress=json.loads((folder/'progress.json').read_text(encoding='utf-8')) if (folder/'progress.json').exists() else {'status':'queued'}
            if active_job==job and active is not None and active.poll() is not None and progress.get('status') not in ('completed','failed','cancelled'):
                progress={**progress,'status':'failed','error':'Python worker exited; see worker.log','exit_code':active.returncode}
            response={'id':job,'progress':progress}
            if (folder/'motorcad_open_status.json').is_file():response['motorcad_open']=json.loads((folder/'motorcad_open_status.json').read_text(encoding='utf-8'))
            if progress.get('status')=='completed' and (folder/'result.json').exists():response['result']=json.loads((folder/'result.json').read_text(encoding='utf-8'))
            if (folder/'error.json').exists():response['error']=json.loads((folder/'error.json').read_text(encoding='utf-8'))
            return self.reply(200,response)
        match=re.fullmatch(r'/api/download/(\d{8}_\d{6}(?:_\d+)?)/(inputs.csv|results.csv|motorcad.csv|result.json|request.json)',path.path)
        if match:
            f=JOBS/match[1]/match[2]
            if not f.is_file():return self.reply(404,{'error':'File not ready'})
            raw=f.read_bytes();self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8' if f.suffix=='.csv' else 'application/json; charset=utf-8');self.send_header('Content-Disposition',f'attachment; filename="{match[1]}_{f.name}"');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        if path.path.startswith('/api/'):return self.reply(404,{'error':'Unknown endpoint'})
        super().do_GET()
    def do_POST(self):
        global active,active_job
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://127.0.0.1:8765','http://localhost:8765'):return self.reply(403,{'error':'Local origin required'})
        try:
            length=int(self.headers.get('Content-Length',0))
            if not 0<length<=524288:raise ValueError('Invalid request length')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError('Expected a JSON object')
            if self.path.startswith('/api/breadloaf/'):
                command=self.path.removeprefix('/api/breadloaf/')
                if command=='start' and ((active and active.poll() is None) or task_worker_active(TaskStore())):
                    raise ValueError('Another calculation worker is active')
                return self.reply(202 if command in ('search','start') else 200,breadloaf_gui.action(command,data))
            if self.path=='/api/task-queue/create':
                job=create_plan(TaskStore(),data.get('title','Task plan'),data.get('tasks',[]))
                return self.reply(200,TaskStore().snapshot(job))
            if self.path=='/api/task-queue/import-checklist':
                job=import_checklist(TaskStore(),data.get('path',str(current_checklist_path())))
                return self.reply(200,TaskStore().snapshot(job))
            if self.path=='/api/task-queue/stop':
                store=TaskStore();store.set_stop(data.get('id'));return self.reply(200,store.snapshot(data.get('id')))
            if self.path=='/api/task-queue/start':
                for key in ('allow_native','resume','reviewed'):
                    if not isinstance(data.get(key,False),bool):raise ValueError(key+' must be boolean')
                retries=data.get('retry_ids',[])
                if not isinstance(retries,list) or not all(isinstance(v,str) for v in retries) or len(retries)!=len(set(retries)):raise ValueError('Distinct retry task IDs required')
                return self.reply(202,launch_task_queue(TaskStore(),data.get('id'),data.get('allow_native',False),
                    data.get('resume',False),retries,data.get('reviewed',False)))
            if self.path=='/api/rotor/preflight':return self.reply(200,preflight(data))
            if self.path=='/api/geometry/spm/preview':
                result=spm_geometry_preview(data)
                folder=ROOT/'outputs/spm_geometry_previews'/str(time.time_ns());folder.mkdir(parents=True)
                write_json(folder/'request.json',data);write_json(folder/'result.json',result)
                return self.reply(200,{**result,'saved_folder':str(folder),'motorcad_solves':0})
            if self.path=='/api/geometry/spm/recipe':
                result=compile_detailed_spm_recipe(data.get('request',{}),data.get('point',{}))
                folder=ROOT/'outputs/spm_geometry_recipes'/str(time.time_ns());folder.mkdir(parents=True)
                write_json(folder/'recipe.json',result)
                return self.reply(200,{**result,'saved_folder':str(folder),'motorcad_solves':0})
            if self.path=='/api/model-support':return self.reply(200,check_model_support(data,'formula'))
            if self.path=='/api/topology/plan':
                # Persist a preparation/checklist only. Never starts native FEA.
                folder=ROOT/'outputs'/('topology_plan_'+str(time.time_ns()))
                result=run_study(data,folder,optimize_available=False)
                return self.reply(200,{'folder':str(folder),'pending_task_count':result['pending_task_count'],'motorcad_solves':0})
            if self.path=='/api/optimize':
                request=validate_formula(data)
                return self.reply(202,{'id':launch_worker(request,'formula_job.py'),'stage':'formula','motorcad_solves':0})
            if self.path=='/api/verification-estimate':
                _,formula,ids=saved_formula(data)
                return self.reply(200,verification_estimate(formula,ids))
            if self.path=='/api/verify':
                job,formula,ids=saved_formula(data)
                request={**formula['request'],'formula_source_job':job,'selected_model_ids':ids}
                if 'open_motorcad_after' in data:request['open_motorcad_after']=data['open_motorcad_after']
                validate(request)
                return self.reply(202,{'id':launch_worker(request,'verify_formula_job.py'),'stage':'verification',
                                      'estimate':verification_estimate(formula,ids)})
            if self.path=='/api/motorcad/open':
                job=data.get('id','')
                if not re.fullmatch(r'\d{8}_\d{6}(?:_\d+)?',job):raise ValueError('Invalid job ID')
                with lock:
                    if active and active.poll() is None:return self.reply(409,{'error':'An analysis is running; open its model after completion'})
                    status_file=JOBS/job/'motorcad_open_status.json'
                    if status_file.is_file():
                        status=json.loads(status_file.read_text(encoding='utf-8'))
                        if status.get('status') in ('queued','opening') and time.time()-status.get('requested_at',status_file.stat().st_mtime)<120:
                            return self.reply(409,{'error':'Motor-CAD model is already opening'})
                    return self.reply(202,queue_open(JOBS/job,data.get('model_id'),data.get('label')))
            if self.path=='/api/jobs':
                request=validate(data)
                with lock:
                    if active and active.poll() is None:return self.reply(409,{'error':'An analysis is already running'})
                    job=time.strftime('%Y%m%d_%H%M%S');folder=JOBS/job
                    if folder.exists():job+='_'+str(time.time_ns()%1000000);folder=JOBS/job
                    folder.mkdir();write_json(folder/'request.json',request);write_json(folder/'progress.json',{'status':'queued'})
                    log=(folder/'worker.log').open('ab')
                    try:active=subprocess.Popen([sys.executable,str(ROOT/'validation/design_job.py'),'--resume',str(folder)],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    finally:log.close()
                    active_job=job
                return self.reply(202,{'id':job})
            if self.path=='/api/cancel':
                job=data.get('id','')
                if not re.fullmatch(r'\d{8}_\d{6}(?:_\d+)?',job) or not (JOBS/job).is_dir():raise ValueError('Invalid job')
                (JOBS/job/'cancel.request').touch();return self.reply(200,{'status':'stop_requested','note':'Stops after current solve completes'})
            return self.reply(404,{'error':'Unknown endpoint'})
        except (ValueError,KeyError,TypeError,FileNotFoundError) as e:return self.reply(400,{'error':str(e)})

if __name__=='__main__':
    print('Motor Design Studio: http://127.0.0.1:8765',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
