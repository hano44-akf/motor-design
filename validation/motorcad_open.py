"""Open a selected, persisted comparison model in a separate visible instance."""
from pathlib import Path
import argparse
import contextlib
import json
import math
import re
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent
JOBS=ROOT/'jobs'


def write_status(folder,data):
    path=folder/'motorcad_open_status.json'
    temp=path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def selected_model(folder,model_id,label=None):
    folder=Path(folder).resolve()
    if folder.parent!=JOBS.resolve() or not re.fullmatch(r'\d{8}_\d{6}(?:_\d+)?',folder.name):raise ValueError('Invalid saved job directory')
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    candidate=next((c for c in result['results'] if c['id']==model_id),None)
    if candidate is None:raise ValueError('Model is not in the saved comparison')
    runs=candidate['runs']
    if label is None:
        op=result['request']['operating_point']
        rated=op.get('nominal_voltage_V',12 if 12 in op['voltages_V'] else op['voltages_V'][0])
        target_temp=result['request'].get('temperatures_C',[20])[0]
        run=min(runs,key=lambda r:(abs(r['input_options']['temperature_C']-target_temp),abs(r['design']['voltage_V']-rated)))
    else:
        run=next((r for r in runs if r['label']==label),None)
        if run is None:raise ValueError('Operating condition is not in the saved model')
    if not re.fullmatch(r'[A-Za-z0-9_-]+',run['label']):raise ValueError('Invalid saved model label')
    path=(folder/(run['label']+'.mot')).resolve()
    if path.parent!=folder or not path.is_file():raise ValueError('Saved .mot model is unavailable')
    return path,run


def queue_open(folder,model_id,label=None):
    folder=Path(folder).resolve();path,run=selected_model(folder,model_id,label)
    status={'status':'queued','model_id':model_id,'label':run['label'],'source_model':str(path),'requested_at':time.time()}
    write_status(folder,status)
    args=[sys.executable,str(Path(__file__).resolve()),'--job',folder.name,'--model',model_id,'--label',run['label']]
    with (folder/'motorcad_open.log').open('ab') as log:
        proc=subprocess.Popen(args,cwd=str(ROOT.parent),stdout=log,stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return {**status,'launcher_pid':proc.pid}


def open_saved(folder,model_id,label):
    import msvcrt
    from ansys.motorcad.core import MotorCAD
    path,run=selected_model(folder,model_id,label)
    lock=(ROOT/'motorcad_execution.lock').open('a+b');mc=None
    try:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        write_status(folder,{'status':'opening','model_id':model_id,'label':run['label']})
        # A review copy protects the persisted comparison artifact from edits.
        copy=folder/('viewer_'+run['label']+'.mot');shutil.copy2(path,copy)
        mc=MotorCAD(open_new_instance=True,keep_instance_open=True)
        mc.set_variable('MessageDisplayState',2);mc.load_from_file(str(copy))
        checks={'DCBusVoltage':run['design']['voltage_V'],'PeakCurrent':run['design']['input_peak_current_A'],
                'PhaseAdvance':run['design'].get('phase_advance_deg',run['readback'].get('PhaseAdvance',0))}
        if 'Airgap' in run.get('geometry_mm',{}):checks['Airgap']=run['geometry_mm']['Airgap']
        actual={key:mc.get_variable(key) for key in checks}
        if any(not math.isclose(actual[k],v,abs_tol=1e-6,rel_tol=1e-7) for k,v in checks.items()):
            raise RuntimeError('Saved Motor-CAD model readback differs from comparison: '+str(actual))
        mc.set_variable('MessageDisplayState',0);mc.set_visible(True)
        write_status(folder,{'status':'opened','model_id':model_id,'label':run['label'],'opened_model':str(copy),
                             'readback':actual,'note':'Saved input configuration opened; no new solve was requested'})
    except Exception as exc:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        write_status(folder,{'status':'failed','model_id':model_id,'label':label,'error':str(exc)})
        raise
    finally:lock.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--job',required=True);parser.add_argument('--model',required=True);parser.add_argument('--label',required=True)
    args=parser.parse_args();open_saved(JOBS/args.job,args.model,args.label)
