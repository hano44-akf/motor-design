"""Sequential background mesh sensitivity study, never a design optimization."""
import argparse
import contextlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import traceback
from study_io import write_json

ROOT=Path(__file__).resolve().parent


def mesh_levels(poles=4,points=240):
    if poles%2 or poles<2 or points<1:raise ValueError('Positive even poles and positive resolution required')
    # Mechanical mesh pitch / rotation step must be an integer ratio.
    base=points*(poles//2)
    levels=[]
    for i in range(3):
        factor=2**i;nodes=base*factor
        levels.append({'id':f'L{i+1}','AirgapMeshPoints_layers':nodes,'AirgapMeshPoints_mesh':nodes,
            'MagnetMeshLength':1./factor,'StatorLamMeshLength':2./factor,'RotorLamMeshLength':2./factor})
    return levels


def run_phase(source,folder):
    import msvcrt
    import low_voltage as solver
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    source=Path(source);reference=json.loads(source.read_text(encoding='utf-8'))
    d=reference['design'];g=reference['geometry_mm'];options=reference['input_options']
    solver.OUT=folder;mc=None;lock=None;rows=[];start=time.time()
    def progress(status,**extra):write_json(folder/'progress.json',{'status':status,'completed_solves':len(rows),'elapsed_s':time.time()-start,**extra})
    try:
        lock=(ROOT/'motorcad_execution.lock').open('a+b')
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        progress('starting');mc,_=solver.start()
        materials=reference['component_materials'];solver.prepare(mc,materials['Stator Lam (Back Iron)'],materials['Magnet'])
        for level in mesh_levels():
            for scale in (0,1):
                if (folder.parent/'cancel.request').exists():raise InterruptedError('Stop requested')
                label=f"{level['id']}_current{scale}";progress('solving',label=label)
                settings={k:v for k,v in level.items() if k!='id'}
                settings.update(CoggingTorqueCalculation=scale==0,TorqueNumberCycles=2,BackEMFNumberCycles=2)
                row=solver.solve(mc,label,d['diameter_mm'],d['length_mm'],d['turns_per_coil'],d['wire_diameter_mm'],
                    d['input_peak_current_A']*scale,d['voltage_V'],240,
                    options={**options,'phase_advance_deg':0},geometry=g,calculation_settings=settings,
                    graph_names=['TorqueVW','TorqueMsVw','CoggingTorque'])
                if row['component_materials']!=materials:raise RuntimeError('Material readback mismatch')
                readback={key:mc.get_variable(key) for key in settings}
                if any(abs(float(readback[k])-float(v))>1e-9 for k,v in settings.items()):raise RuntimeError('Mesh/calculation settings changed during solve')
                row['mesh_readback']=readback;write_json(folder/(label+'.json'),row)
                v=row['values']
                rows.append({'label':label,'mesh_level':level,'current_scale':scale,'torque_Nm':v.get('Shaft Torque'),
                    'average_torque_MsVw_Nm':v.get('Average torque (MsVw)'),
                    'torque_pp_MsVw_Nm':v.get('Torque Ripple (MsVw)'),
                    'cogging_pp_Vw_Nm':v.get('Cogging Torque Ripple (Vw)') if scale==0 else None,
                    'ripple_pct':v.get('Torque Ripple (MsVw) [%]') if scale else None,
                    'iron_B_T':{k:value for k,value in v.items() if 'Flux Density (maximum)' in k},
                    'solver_s':row['timings']['solver_s'],'available_graphs':list(row.get('graphs',{})),
                    'graph_errors':row.get('graph_errors',{}),'output':str(folder/(label+'.json'))})
                write_json(folder/'partial_results.json',rows)
        changes=[]
        for scale in (0,1):
            group=[r for r in rows if r['current_scale']==scale]
            for old,new in zip(group,group[1:]):
                diffs={}
                for field in ('average_torque_MsVw_Nm','torque_pp_MsVw_Nm','cogging_pp_Vw_Nm'):
                    a,b=old.get(field),new.get(field)
                    if isinstance(a,(int,float)) and isinstance(b,(int,float)):
                        diffs[field]={'absolute':b-a,'relative_to_previous':(b-a)/abs(a) if abs(a)>1e-12 else None}
                changes.append({'current_scale':scale,'from':old['mesh_level']['id'],'to':new['mesh_level']['id'],'changes':diffs})
        write_json(folder/'result.json',{'status':'completed','runs':rows,'changes':changes,'elapsed_s':time.time()-start,
            'convergence_qualified':False,'scope':'Three-level simultaneous airgap and region mesh sensitivity; no automatic convergence certification or current retuning. Native graph IDs may be unavailable and are logged independently.'})
        progress('completed')
    except BaseException as exc:
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('failed');raise
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        if lock:lock.close()


def run_batch(folder):
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'));completed=[];start=time.time()
    try:
        for source in manifest['sources']:
            if (folder/'cancel.request').exists():raise InterruptedError('Stop requested')
            write_json(folder/'progress.json',{'status':'running','active_phase':source['id'],'completed_phases':completed,'started_unix':start})
            with (folder/(source['id']+'.log')).open('ab') as log:
                child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--source',str(ROOT/source['calibration']),
                    '--output',str(folder/source['id'])],cwd=ROOT.parent,stdout=log,stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                write_json(folder/'active_child.json',{'pid':child.pid,'phase':source['id']})
                try:code=child.wait(timeout=5400)
                except subprocess.TimeoutExpired:
                    child.terminate();raise RuntimeError('Mesh phase timed out; inspect native instance before restarting')
                if code:raise RuntimeError('Mesh phase failed: '+source['id'])
            completed.append(source['id'])
        write_json(folder/'progress.json',{'status':'completed','completed_phases':completed,'started_unix':start,'elapsed_s':time.time()-start})
    except BaseException as exc:
        write_json(folder/'progress.json',{'status':'failed','completed_phases':completed,'error':str(exc),'started_unix':start,'elapsed_s':time.time()-start})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',type=Path);parser.add_argument('--source',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.batch:run_batch(args.batch)
    elif args.source and args.output:run_phase(args.source,args.output)
    else:parser.error('Expected batch or source/output')
