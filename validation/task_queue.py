"""Detached sequential task worker and CLI. Default execution never enables FEA."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from task_store import TaskStore,DEFAULT_DB,NATIVE,import_checklist,ROOT
from task_adapters import prepare_spec,execute
from study_io import write_json


@contextlib.contextmanager
def worker_lock(db_path):
    handle=Path(db_path).with_suffix('.worker.lock').open('a+b')
    try:
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as exc:raise ValueError('A task worker is already active for this store') from exc
        else:
            import fcntl
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc:raise ValueError('A task worker is already active for this store') from exc
        yield
    finally:handle.close()


def create_plan(store,title,tasks):
    return store.create(title,[prepare_spec(spec) for spec in tasks])


def run(store,job,allow_native=False,resume=False,retry_ids=(),reviewed=False):
    with worker_lock(store.path):
        store.begin_worker(job)
        if resume:store.set_stop(job,False)
        try:
            for ident in retry_ids:store.retry(job,ident,reviewed)
        except BaseException:
            store.finish_worker(job);raise
        while True:
            task=store.claim(job,allow_native)
            if task is None:break
            attempt_dir=Path(task['output_dir']);output=attempt_dir/'output'
            envelope={'kind':task['kind'],'payload':task['payload'],'attempt':task['attempt'],'output_dir':str(output)}
            write_json(attempt_dir/'task_input.json',envelope)
            process=None;timed_out=False;code=None
            try:
                with (attempt_dir/'worker.log').open('ab') as log:
                    process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--child',str(attempt_dir/'task_input.json')],
                        cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    store.child_started(job,task['id'],task['attempt'],process.pid)
                    started=time.monotonic();stop_signalled=False
                    while process.poll() is None:
                        if time.monotonic()-started>task['timeout_s']:
                            timed_out=True;process.terminate();process.wait(timeout=20);break
                        if task['kind'] in NATIVE and not stop_signalled and store.is_stopped(job):
                            # Both native conventions are supported. Existing
                            # scripts stop at the next solve boundary.
                            (attempt_dir/'cancel.request').touch()
                            output.mkdir(exist_ok=True);(output/'cancel.request').touch();stop_signalled=True
                        time.sleep(.2)
                    code=process.returncode
                if timed_out:raise RuntimeError('Task timeout; review partial output and any native instance before retry')
                if code:raise RuntimeError(f'Task child exited {code}; see {attempt_dir / "worker.log"}')
                receipt=json.loads((output/'receipt.json').read_text(encoding='utf-8'))
                store.finish(job,task['id'],task['attempt'],output=receipt)
            except BaseException as exc:
                if process is not None and process.poll() is None:
                    process.terminate()
                    with contextlib.suppress(Exception):process.wait(timeout=20)
                store.finish(job,task['id'],task['attempt'],error=str(exc))
                if task['kind'] in NATIVE or isinstance(exc,(KeyboardInterrupt,SystemExit)):break
        return store.finish_worker(job)


def launch(store,job,allow_native=False,resume=False,retry_ids=(),reviewed=False):
    snapshot=store.snapshot(job)
    if not snapshot['implementation_compatible']:raise ValueError('Implementation changed; register a new plan')
    for ident in retry_ids:
        task=next((t for t in snapshot['tasks'] if t['id']==ident),None)
        if not task or task['state']!='failed':raise ValueError('Select failed task IDs only')
        if task['reason']=='input_changed':raise ValueError('Input changed; register a new plan')
        if (task['kind'] in NATIVE or task['reason'] in ('interrupted_worker_review_required','completed_artifact_changed')) and not reviewed:
            raise ValueError('Review partial results/process before retry')
    # Detect an already running queue before reporting a detached start.
    with worker_lock(store.path):pass
    log_dir=store.path.parent/'worker_logs';log_dir.mkdir(exist_ok=True)
    log_path=log_dir/(job+'_'+str(time.time_ns())+'.log')
    command=[sys.executable,str(Path(__file__).resolve()),'--db',str(store.path),'--run',job]
    if allow_native:command.append('--allow-native')
    if resume:command.append('--resume')
    if reviewed:command.append('--reviewed')
    for task in retry_ids:command.extend(['--retry',task])
    with log_path.open('ab') as log:
        process=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return {'id':job,'worker_pid':process.pid,'worker_log':str(log_path),'native_enabled':allow_native,
            'note':'Detached worker started; task status and errors are persisted. No completion wait.'}


def worker_active(store):
    try:
        with worker_lock(store.path):return False
    except ValueError:return True


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,default=DEFAULT_DB)
    parser.add_argument('--plan',type=Path);parser.add_argument('--import-checklist',type=Path)
    parser.add_argument('--run');parser.add_argument('--status');parser.add_argument('--stop')
    parser.add_argument('--allow-native',action='store_true');parser.add_argument('--resume',action='store_true')
    parser.add_argument('--retry',action='append',default=[]);parser.add_argument('--reviewed',action='store_true')
    parser.add_argument('--child',type=Path)
    args=parser.parse_args()
    if args.child:
        data=json.loads(args.child.read_text(encoding='utf-8'));out=Path(data['output_dir'])
        try:
            receipt=execute(data['kind'],data['payload'],out,data['attempt']);write_json(out/'receipt.json',receipt)
        except BaseException as exc:
            out.mkdir(exist_ok=True,parents=True);write_json(out/'task_error.json',{'error':str(exc),'traceback':traceback.format_exc()});raise
        return
    store=TaskStore(args.db)
    if args.plan:
        data=json.loads(args.plan.read_text(encoding='utf-8'));result={'id':create_plan(store,data['title'],data['tasks'])}
    elif args.import_checklist:result={'id':import_checklist(store,args.import_checklist)}
    elif args.status:result=store.snapshot(args.status)
    elif args.stop:store.set_stop(args.stop);result=store.snapshot(args.stop)
    elif args.run:result=run(store,args.run,args.allow_native,args.resume,args.retry,args.reviewed)
    else:result=store.list_jobs()
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main()
