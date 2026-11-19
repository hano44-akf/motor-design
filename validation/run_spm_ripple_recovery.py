"""Isolated per-case FEA with owned-process watchdog and geometry rejection."""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import psutil
from magnet_boundary_check import check_region
from study_io import write_json
from spm_ripple import acceptance

ROOT=Path(__file__).resolve().parent
GEOMETRY_ERRORS=('lines/arc intersection','new point added into undefined region','invalid geometry')


def stop_owned(worker):
    """Stop only this spawned worker's Motor-CAD descendants, never other apps."""
    with contextlib.suppress(psutil.NoSuchProcess):
        for process in psutil.Process(worker.pid).children(recursive=True):
            with contextlib.suppress(psutil.NoSuchProcess,psutil.AccessDenied):
                if process.name().lower()=='motorcad.exe':
                    process.terminate()
                    try:process.wait(timeout=5)
                    except psutil.TimeoutExpired:process.kill()
    if worker.poll() is None:
        worker.terminate()
        try:worker.wait(timeout=5)
        except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=5)


def case_run(folder,index):
    import low_voltage as solver
    from validate_spm_ripple import checked
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'));case=plan['cases'][index]
    attempt=folder/case['id'];mc=None;started=time.time()
    try:
        source=Path(case['source_folder']);model=source/case.get('source_model_name',case['id']+'.mot')
        for file,expected in [(model,case['source_model_sha256']),
                (folder/(case['id']+'_snapshot.json'),case['snapshot_sha256']),
                (folder/(case['id']+'_proxy.json'),case['prediction_sha256'])]:
            if hashlib.sha256(file.read_bytes()).hexdigest()!=expected:raise ValueError('Frozen input changed: '+str(file))
        snapshot=json.loads((folder/(case['id']+'_snapshot.json')).read_text(encoding='utf-8'))
        boundary=check_region(snapshot['magnet_region'])
        if not boundary['passed']:raise ValueError('Saved magnet boundary failed self-intersection check')
        local_model=attempt/(case['id']+'.mot');shutil.copy2(model,local_model)
        write_json(attempt/'progress.json',{'phase':'starting','started_unix':started})
        mc,_=solver.start();mc.load_from_file(str(local_model))
        db=attempt/'working_materials.mdb';shutil.copy2(source/'working_materials.mdb',db)
        mc.select_material_database(str(db),False)
        mc.clear_message_log();checked(mc,snapshot['expected_native']);mc.reset_adaptive_geometry()
        tree=mc.get_geometry_tree()._to_json();write_json(attempt/'native_geometry.json',tree)
        magnets=[m for m in tree['regions'].values() if m.get('region_type')=='Magnet']
        if len(magnets)!=1:raise ValueError('Native topology changed')
        boundary=check_region(magnets[0]);write_json(attempt/'geometry_check.json',boundary)
        if not boundary['passed']:raise ValueError('Rebuilt magnet boundary failed self-intersection check')
        old=snapshot['magnet_region']['entities'];new=magnets[0]['entities']
        if len(old)!=len(new):raise ValueError('Native boundary changed since prediction')
        for a,b in zip(old,new):
            if a['type']!=b['type']:raise ValueError('Boundary type changed')
            for field in ('start','end')+ (('centre',) if a['type']=='arc' else ()):
                if any(abs(a[field][xy]-b[field][xy])>1e-6 for xy in ('x','y')):raise ValueError('Boundary coordinate changed')
        for k,v in snapshot['expected_native'].items():
            if abs(mc.get_variable(k)-v)>1e-6:raise ValueError('Native input changed: '+k)
        materials={'Stator Lam (Back Iron)':'POSCO | 50PN470','Stator Lam (Tooth)':'POSCO | 50PN470',
            'Rotor Lam (Back Iron)':'POSCO | 50PN470','Magnet':'JL Mag Rare-Earth | N48UH'}
        if any(mc.get_component_material(k)!=v for k,v in materials.items()):raise ValueError('Native material mismatch')
        settings={'TorquePointsPerCycle':240,'TorqueNumberCycles':2,'BackEMFPointsPerCycle':240,'BackEMFNumberCycles':2,
            'AirgapMeshPoints_layers':960,'AirgapMeshPoints_mesh':960,'MagnetMeshLength':.5,'StatorLamMeshLength':1,'RotorLamMeshLength':1}
        for k,v in settings.items():mc.set_variable(k,v)
        if any(abs(mc.get_variable(k)-v)>1e-6 for k,v in settings.items()):raise ValueError('Mesh settings mismatch')
        mc.save_to_file(str(local_model));write_json(attempt/'progress.json',{'phase':'solving','started_unix':started})
        start=time.perf_counter();mc.do_magnetic_calculation();solver_s=time.perf_counter()-start
        csv=attempt/(case['id']+'.csv');mc.export_results('EMagnetic',str(csv));values,flag=solver.parse_csv(csv)
        if any(abs(mc.get_variable(k)-v)>1e-6 for k,v in snapshot['expected_native'].items()):raise ValueError('Inputs changed during FEA')
        mc.save_to_file(str(local_model));graphs={}
        for name in ('TorqueMsVw','TorqueVW'):
            try:x,y=mc.get_magnetic_graph(name);graphs[name]={'x':list(map(float,x)),'y':list(map(float,y))}
            except Exception as exc:graphs[name]={'error':str(exc)}
        actual=values.get('Torque Ripple (MsVw) [%]')
        write_json(attempt/'result.json',{'status':'completed','id':case['id'],'rotor_id':case['rotor_id'],
            'predicted_ripple_pct':case['predicted_ripple_pct'],'actual_ripple_pct':actual,
            'acceptance':acceptance(case['predicted_ripple_pct'],actual),'values':values,'graphs':graphs,
            'solver_s':solver_s,'elapsed_s':time.time()-started,'geometry_check':boundary,'voltage_limit_exceeded':flag,
            'production_qualified':False})
    except BaseException as exc:
        write_json(attempt/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});raise
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()


def run(folder):
    import msvcrt
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    if (folder/'progress.json').exists():raise ValueError('Fresh recovery folder required')
    lock=(ROOT/'motorcad_execution.lock').open('a+b');outcomes=[];started=time.time()
    def progress(status,**extra):write_json(folder/'progress.json',{'status':status,'started_unix':started,
        'elapsed_s':time.time()-started,'planned_fea':len(plan['cases']),
        'completed_fea':sum(r.get('status')=='completed' for r in outcomes),'failed_cases':sum(r.get('status')!='completed' for r in outcomes),**extra})
    try:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        for index,case in enumerate(plan['cases']):
            if (folder/'cancel.request').exists():progress('stopped');return
            attempt=folder/case['id'];attempt.mkdir();progress('running',active_case=case['id'])
            with (attempt/'worker.log').open('wb') as log:
                child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--output',str(folder),'--case-index',str(index)],
                    cwd=ROOT.parent,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                write_json(attempt/'child.json',{'pid':child.pid});t=time.time();reason=None
                while child.poll() is None:
                    if time.time()-t>plan['per_case_timeout_s']:reason='case_timeout';break
                    if (folder/'cancel.request').exists():reason='stop_requested';break
                    for file in attempt.rglob('messageLog_*.txt'):
                        text=file.read_text(encoding='utf-8',errors='replace').lower()
                        if any(s in text for s in GEOMETRY_ERRORS):reason='native_geometry_warning';break
                    if reason:break
                    time.sleep(2)
                if reason:stop_owned(child)
            if not reason:
                for file in attempt.rglob('messageLog_*.txt'):
                    text=file.read_text(encoding='utf-8',errors='replace').lower()
                    if any(s in text for s in GEOMETRY_ERRORS):reason='native_geometry_warning';break
            result=attempt/'result.json'
            if not reason and child.returncode==0 and result.exists():row=json.loads(result.read_text(encoding='utf-8'))
            else:row={'status':'failed','id':case['id'],'rotor_id':case['rotor_id'],'reason':reason or 'child_failed','exit_code':child.returncode}
            write_json(attempt/'outcome.json',row);outcomes.append(row);write_json(folder/'partial_results.json',outcomes)
        write_json(folder/'result.json',{'status':'completed_with_failures' if any(r['status']!='completed' for r in outcomes) else 'completed',
            'outcomes':outcomes,'elapsed_s':time.time()-started,'production_qualified':False,
            'scope':plan.get('scope','Flat and geometry-valid Breadloaf only. Existing four FEA cases are preserved, not rerun.')})
        progress('completed_with_failures' if any(r['status']!='completed' for r in outcomes) else 'completed')
    except BaseException as exc:write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('failed');raise
    finally:lock.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--case-index',type=int)
    a=p.parse_args();case_run(a.output,a.case_index) if a.case_index is not None else run(a.output)
