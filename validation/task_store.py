"""Durable local task DAG. No solver imports or application launch side effects."""
import contextlib
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

ROOT=Path(__file__).resolve().parent.parent
DEFAULT_DB=ROOT/'outputs/task_queue/tasks.sqlite'
KINDS={'mock','formula','motorcad_verify','motorcad_diagnostic','motorcad_mesh','manual_check'}
NATIVE={'motorcad_verify','motorcad_diagnostic','motorcad_mesh'}


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def digest(value):return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def implementation_digest():
    h=hashlib.sha256()
    for file in sorted((ROOT/'validation').glob('*.py')):
        h.update(file.name.encode());h.update(file.read_bytes())
    return h.hexdigest()


def project_file(path):
    path=Path(path);path=(ROOT/path if not path.is_absolute() else path).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('Existing project file required: '+str(path))
    return path


def file_digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


class TaskStore:
    def __init__(self,path=DEFAULT_DB):
        self.path=Path(path).resolve();self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            INSERT OR IGNORE INTO meta VALUES('schema','motor-task-store-v1');
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, signature TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
              state TEXT NOT NULL, stop_requested INTEGER NOT NULL DEFAULT 0,
              code_hash TEXT NOT NULL, manifest_json TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(
              job_id TEXT NOT NULL,id TEXT NOT NULL,kind TEXT NOT NULL,payload_json TEXT NOT NULL,
              input_hash TEXT NOT NULL,files_json TEXT NOT NULL,deps_json TEXT NOT NULL,
              state TEXT NOT NULL,reason TEXT,attempts INTEGER NOT NULL DEFAULT 0,
              estimate_s REAL,timeout_s REAL NOT NULL,output_json TEXT,error TEXT,
              PRIMARY KEY(job_id,id),FOREIGN KEY(job_id) REFERENCES jobs(id));
            CREATE TABLE IF NOT EXISTS attempts(
              job_id TEXT NOT NULL,task_id TEXT NOT NULL,number INTEGER NOT NULL,state TEXT NOT NULL,
              started REAL NOT NULL,ended REAL,pid INTEGER,output_dir TEXT NOT NULL,error TEXT,
              PRIMARY KEY(job_id,task_id,number));
            CREATE TABLE IF NOT EXISTS events(
              number INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,task_id TEXT,event TEXT NOT NULL,
              created REAL NOT NULL,details_json TEXT NOT NULL);
            ''')
            if db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]!='motor-task-store-v1':raise ValueError('Unsupported task store schema')

    @contextlib.contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=20);db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA journal_mode=WAL')
        try:
            yield db;db.commit()
        except BaseException:db.rollback();raise
        finally:db.close()

    def _event(self,db,job,task,event,details=None):
        db.execute('INSERT INTO events(job_id,task_id,event,created,details_json) VALUES(?,?,?,?,?)',
                   (job,task,event,time.time(),encoded(details or {})))

    def create(self,title,tasks):
        if not isinstance(title,str) or not title.strip():raise ValueError('Job title required')
        if not isinstance(tasks,list) or not 1<=len(tasks)<=4096:raise ValueError('Use 1..4096 tasks')
        normalized=[];seen=set()
        for spec in tasks:
            ident=spec.get('id');kind=spec.get('kind')
            if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_-]{0,95}',ident) or ident in seen:raise ValueError('Invalid/duplicate task ID')
            seen.add(ident)
            if kind not in KINDS:raise ValueError('Unknown task kind')
            payload=spec.get('payload',{})
            if not isinstance(payload,dict):raise ValueError('Task payload must be an object')
            deps=spec.get('depends_on',[])
            if not isinstance(deps,list) or len(deps)!=len(set(deps)) or not all(isinstance(v,str) for v in deps):raise ValueError('Distinct dependency IDs required')
            estimates=spec.get('estimate_s');timeout=spec.get('timeout_s',3600)
            for name,value in (('estimate_s',estimates),('timeout_s',timeout)):
                if value is None and name=='estimate_s':continue
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('Positive duration required: '+name)
            files={str(project_file(p).relative_to(ROOT)):file_digest(project_file(p)) for p in spec.get('input_files',[])}
            entry={'id':ident,'kind':kind,'payload':payload,'depends_on':deps,'files':files,
                   'estimate_s':estimates,'timeout_s':timeout}
            entry['input_hash']=digest({k:entry[k] for k in ('kind','payload','depends_on','files')})
            normalized.append(entry)
        graph={t['id']:t['depends_on'] for t in normalized};resolved=set()
        while len(resolved)<len(graph):
            ready=[key for key,deps in graph.items() if key not in resolved and set(deps)<=resolved]
            if not ready:raise ValueError('Unknown dependency or dependency cycle')
            resolved.update(ready)
        # Identical executable inputs within a graph must share an explicit
        # task/dependency, rather than silently renaming requested model IDs.
        hashes=[t['input_hash'] for t in normalized if t['kind']!='manual_check']
        if len(hashes)!=len(set(hashes)):raise ValueError('Duplicate executable inputs: share one task via dependencies')
        code=implementation_digest();manifest={'schema':'motor-task-plan-v1','tasks':normalized,'code_hash':code}
        signature=digest(manifest);job='job_'+uuid.uuid4().hex
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT id FROM jobs WHERE signature=?',(signature,)).fetchone()
            if previous:return previous['id']
            now=time.time()
            db.execute('INSERT INTO jobs(id,signature,title,state,code_hash,manifest_json,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                       (job,signature,title,'planned',code,encoded(manifest),now,now))
            for t in normalized:
                db.execute('INSERT INTO tasks(job_id,id,kind,payload_json,input_hash,files_json,deps_json,state,reason,estimate_s,timeout_s) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (job,t['id'],t['kind'],encoded(t['payload']),t['input_hash'],encoded(t['files']),encoded(t['depends_on']),
                            'blocked' if t['kind']=='manual_check' else 'planned',
                            'execution_recipe_required' if t['kind']=='manual_check' else None,t['estimate_s'],t['timeout_s']))
            self._event(db,job,None,'plan_created',{'tasks':len(tasks),'native_execution_started':False})
        return job

    def snapshot(self,job):
        with self.connect() as db:
            header=db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not header:raise ValueError('Unknown task job')
            tasks=[dict(r) for r in db.execute('SELECT * FROM tasks WHERE job_id=? ORDER BY rowid',(job,))]
            attempts=[dict(r) for r in db.execute('SELECT * FROM attempts WHERE job_id=? ORDER BY started',(job,))]
        for task in tasks:
            for key in ('payload','files','deps','output'):
                task[key]=json.loads(task.pop(key+'_json')) if task.get(key+'_json') else None
        states={}
        for task in tasks:states[task['state']]=states.get(task['state'],0)+1
        remaining=[t for t in tasks if t['state'] in ('planned','ready','running','blocked')]
        unknown=sum(t['estimate_s'] is None for t in remaining)
        estimate=sum(t['estimate_s'] or 0 for t in remaining)
        return {'schema':'motor-task-status-v1','id':job,'title':header['title'],'state':header['state'],
                'implementation_compatible':header['code_hash']==implementation_digest(),
                'stop_requested':bool(header['stop_requested']),'created':header['created'],'updated':header['updated'],
                'counts':states,'tasks':tasks,'attempts':attempts,
                'completed_tasks':states.get('completed',0),'total_tasks':len(tasks),
                'estimated_remaining_s':estimate if not unknown else None,
                'known_estimate_sum_s':estimate,'unestimated_tasks':unknown,
                'estimate_scope':'Sum of remaining task estimates, not a live per-solve ETA. Any unestimated/blocked recipe prevents a complete ETA.'}

    def list_jobs(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,title,state,stop_requested,created,updated FROM jobs WHERE state!='superseded' ORDER BY created DESC")]

    def supersede_outdated_checklists(self,replacement):
        """Remove obsolete thermal/structure bundles from the active plan list.

        Original tasks, file hashes, attempts and history are never rewritten.
        """
        superseded=[]
        with self.connect() as db:
            for job in db.execute("SELECT id FROM jobs WHERE id!=? AND state!='superseded'",(replacement,)).fetchall():
                rows=db.execute('SELECT id,kind FROM tasks WHERE job_id=?',(job['id'],)).fetchall()
                if rows and all(t['kind']=='manual_check' for t in rows) and any(t['id'].endswith('_safety') for t in rows):
                    db.execute("UPDATE jobs SET state='superseded',updated=? WHERE id=?",(time.time(),job['id']))
                    self._event(db,job['id'],None,'plan_superseded',{'replacement':replacement,'reason':'Thermal/structural scope removed by user'})
                    superseded.append(job['id'])
        return superseded

    def artifact(self,job,task,attempt,name):
        allowed={'result.json','request.json','inputs.csv','results.csv','motorcad.csv','receipt.json',
                 'task_error.json','domain_request.json','model_support.json','worker.log'}
        if name not in allowed or isinstance(attempt,bool) or not isinstance(attempt,int) or attempt<1:
            raise ValueError('Unknown artifact')
        with self.connect() as db:
            row=db.execute('SELECT output_dir FROM attempts WHERE job_id=? AND task_id=? AND number=?',(job,task,attempt)).fetchone()
        if not row:raise ValueError('Unknown task attempt')
        root=Path(row['output_dir']).resolve();path=(root/name if name=='worker.log' else root/'output'/name).resolve()
        if not path.is_relative_to(root) or not path.is_relative_to(self.path.parent/'artifacts') or not path.is_file():
            raise ValueError('Artifact not available')
        return path

    def set_stop(self,job,value=True):
        with self.connect() as db:
            if not db.execute('UPDATE jobs SET stop_requested=?,updated=? WHERE id=?',(int(value),time.time(),job)).rowcount:raise ValueError('Unknown task job')
            self._event(db,job,None,'stop_requested' if value else 'resume_requested')

    def is_stopped(self,job):
        with self.connect() as db:
            row=db.execute('SELECT stop_requested FROM jobs WHERE id=?',(job,)).fetchone()
            if not row:raise ValueError('Unknown task job')
            return bool(row[0])

    def begin_worker(self,job):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            header=db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
            if not header:raise ValueError('Unknown task job')
            if header['code_hash']!=implementation_digest():raise ValueError('Implementation changed; create a new plan instead of mixing versions')
            for row in db.execute("SELECT id,output_json FROM tasks WHERE job_id=? AND state='completed'",(job,)).fetchall():
                receipt=json.loads(row['output_json']) if row['output_json'] else {}
                file=Path(receipt.get('result_file',''))
                if not file.is_file() or file_digest(file)!=receipt.get('result_sha256'):
                    db.execute("UPDATE tasks SET state='failed',reason='completed_artifact_changed',error='Saved completed result is missing or changed' WHERE job_id=? AND id=?",(job,row['id']))
                    self._event(db,job,row['id'],'completed_artifact_changed')
            # A lost worker may have left an active solver child. Never reclaim
            # such work automatically or repeat it under another worker.
            lost=db.execute("SELECT id FROM tasks WHERE job_id=? AND state='running'",(job,)).fetchall()
            for row in lost:
                db.execute("UPDATE tasks SET state='failed',reason='interrupted_worker_review_required',error='Prior worker exited without committing task result' WHERE job_id=? AND id=?",(job,row['id']))
                db.execute("UPDATE attempts SET state='interrupted',ended=?,error='Worker interrupted; inspect any child process before retry' WHERE job_id=? AND task_id=? AND ended IS NULL",(time.time(),job,row['id']))
                self._event(db,job,row['id'],'interrupted_worker')
            db.execute("UPDATE jobs SET state='running',updated=? WHERE id=?",(time.time(),job))
            self._event(db,job,None,'worker_started')

    def claim(self,job,allow_native=False):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT stop_requested FROM jobs WHERE id=?',(job,)).fetchone()[0]:return None
            rows=[dict(r) for r in db.execute('SELECT * FROM tasks WHERE job_id=? ORDER BY rowid',(job,))]
            states={t['id']:t['state'] for t in rows}
            native_failure=any(t['kind'] in NATIVE and t['state']=='failed' and t['reason'] in
                               ('interrupted_worker_review_required','execution_failed') for t in rows)
            for row in rows:
                if row['state'] not in ('planned','ready','blocked') or row['kind']=='manual_check':continue
                deps=json.loads(row['deps_json'])
                reason=None
                if any(states[d]!='completed' for d in deps):reason='dependency_not_completed'
                elif row['kind'] in NATIVE and not allow_native:reason='native_execution_not_enabled'
                elif row['kind'] in NATIVE and native_failure:reason='prior_native_failure_review_required'
                if reason:
                    db.execute("UPDATE tasks SET state='blocked',reason=? WHERE job_id=? AND id=?",(reason,job,row['id']));continue
                files=json.loads(row['files_json'])
                if any(not (ROOT/p).is_file() or file_digest(ROOT/p)!=h for p,h in files.items()):
                    db.execute("UPDATE tasks SET state='failed',reason='input_changed',error='Input file missing or hash changed' WHERE job_id=? AND id=?",(job,row['id']))
                    self._event(db,job,row['id'],'input_changed');continue
                number=row['attempts']+1
                out=self.path.parent/'artifacts'/job/row['id']/f'attempt_{number:03d}'
                out.mkdir(parents=True,exist_ok=False)
                db.execute("UPDATE tasks SET state='running',reason=NULL,error=NULL,attempts=? WHERE job_id=? AND id=?",(number,job,row['id']))
                db.execute('INSERT INTO attempts(job_id,task_id,number,state,started,output_dir) VALUES(?,?,?,?,?,?)',(job,row['id'],number,'running',time.time(),str(out)))
                self._event(db,job,row['id'],'task_started',{'attempt':number,'output_dir':str(out)})
                return {**row,'payload':json.loads(row['payload_json']),'attempt':number,'output_dir':str(out)}
        return None

    def child_started(self,job,task,attempt,pid):
        with self.connect() as db:db.execute('UPDATE attempts SET pid=? WHERE job_id=? AND task_id=? AND number=?',(pid,job,task,attempt))

    def finish(self,job,task,attempt,output=None,error=None):
        state='failed' if error else 'completed'
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state,attempts FROM tasks WHERE job_id=? AND id=?',(job,task)).fetchone()
            if not row or row['state']!='running' or row['attempts']!=attempt:raise ValueError('Stale task completion')
            db.execute('UPDATE tasks SET state=?,reason=?,error=?,output_json=? WHERE job_id=? AND id=?',
                       (state,'execution_failed' if error else None,error,encoded(output) if output else None,job,task))
            db.execute('UPDATE attempts SET state=?,ended=?,error=? WHERE job_id=? AND task_id=? AND number=?',(state,time.time(),error,job,task,attempt))
            db.execute('UPDATE jobs SET updated=? WHERE id=?',(time.time(),job))
            self._event(db,job,task,'task_'+state,{'attempt':attempt,'error':error})

    def retry(self,job,task,reviewed=False):
        # Called only while the global queue worker lock is held by the caller.
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM tasks WHERE job_id=? AND id=?',(job,task)).fetchone()
            if not row or row['state']!='failed':raise ValueError('Only failed tasks can be retried')
            if (row['kind'] in NATIVE or row['reason'] in ('interrupted_worker_review_required','completed_artifact_changed')) and not reviewed:
                raise ValueError('Inspect prior child process and partial results before native/interrupted retry')
            if row['reason']=='input_changed':raise ValueError('Input changed: create a new plan')
            db.execute("UPDATE tasks SET state='planned',reason=NULL,error=NULL WHERE job_id=? AND id=?",(job,task))
            self._event(db,job,task,'retry_requested',{'reviewed':reviewed})

    def finish_worker(self,job):
        snapshot=self.snapshot(job);counts=snapshot['counts']
        state=('completed' if snapshot['completed_tasks']==snapshot['total_tasks'] else
               'stopped' if snapshot['stop_requested'] else 'failed' if counts.get('failed') else 'blocked')
        with self.connect() as db:
            db.execute('UPDATE jobs SET state=?,updated=? WHERE id=?',(state,time.time(),job))
            self._event(db,job,None,'worker_finished',{'state':state})
        return self.snapshot(job)


def import_checklist(store,path):
    path=project_file(path);data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema')!='deferred-motor-validation-v1':raise ValueError('Unsupported checklist schema')
    from verification_scope import apply_scope
    data=apply_scope(data)
    tasks=[{'id':t['id'],'kind':'manual_check','payload':t,'depends_on':t.get('depends_on',[]),'input_files':[str(path)]} for t in data['tasks']]
    return store.create('Imported verification preparation checklist',tasks)
