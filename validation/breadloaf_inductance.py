"""Isolated Small Signal development experiment. One job, not PWM certification."""
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
from study_io import write_json

ROOT=Path(__file__).resolve().parent
SETTINGS={'BackEMFCalculation':False,'TorqueCalculation':False,'CoggingTorqueCalculation':False,
          'TorqueSpeedCalculation':False,'DemagnetizationCalc':False,'BPMShortCircuitCalc':False,
          'ElectromagneticForcesCalc_OC':False,'ElectromagneticForcesCalc_Load':False,
          'InductanceCalc':True,'InductanceCalcMethod_BPM':1,'InductanceSolver_BPM':0,
          'InductanceNumberCycles':1,'InductancePointsPerCycle':24,
          'PlotAllInductancePhases':True,'PlotSmallSignalBiasCurrents':True}
GRAPH_NAMES=([f'SelfInductancePh{i}' for i in range(1,4)]+
             [f'MutualInductance{i}Ph{j}' for i in range(1,4) for j in range(1,4) if i!=j]+
             [f'SelfInductanceDifferentialPh{i}' for i in range(1,4)]+
             [f'MutualInductanceDifferential{i}Ph{j}' for i in range(1,4) for j in range(1,4) if i!=j]+
             [f'SmallSignalInductanceCurrentPh{i}' for i in range(1,4)])


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare(source,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Fresh output folder required')
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    plan=load(source/'plan.json');result=load(source/'result.json')
    complete=[r for r in result['outcomes'] if r['status']=='completed']
    if len(complete)!=1:raise ValueError('Exactly one verified candidate required')
    name=complete[0]['id'];snapshot=source/(name+'_snapshot.json')
    frozen=next(c for c in plan['cases'] if c['id']==name)
    if sha(snapshot)!=frozen['snapshot_sha256']:raise ValueError('Frozen source snapshot changed')
    model=source/name/(name+'.mot');db=model.parent/'working_materials.mdb'
    if not model.is_file() or not db.is_file():raise ValueError('Verified model/material database missing')
    data={'schema':'breadloaf-small-signal-experiment-v1','candidate_id':name,
          'source_batch':str(source),'source_model':str(model),'source_database':str(db),'source_snapshot':str(snapshot),
          'model_sha256':sha(model),'database_sha256':sha(db),'snapshot_sha256':sha(snapshot),
          'settings':SETTINGS,'planned_fea':1,'case_timeout_s':900,'estimated_duration_minutes':[2,6],
          'estimate_basis':'Provisional first-run allowance; not measured Small Signal timing.',
          'mapping_evidence':'Installed v261 .mot keys and RPC readback; enum 1 Small Signal / solver 0 Full remains subject to output validation.',
          'graph_name_evidence':'Candidate identifiers found in installed BasicFramework.bpl; RPC acceptance/data content checked after solve.',
          'qualified':False,'pwm_ripple_certified':False,
          'scope':'24 points/full electrical cycle at the verified bias current. No mesh/angle convergence or HF model qualification.'}
    output.mkdir(parents=True);write_json(output/'plan.json',data);return data


def configure(mc,plan):
    expected=json.loads(Path(plan['source_snapshot']).read_text(encoding='utf-8'))['expected_native']
    if mc.get_variable('MagPhases')!=3:raise ValueError('Three-phase Small Signal model required')
    for key,value in expected.items():
        if abs(mc.get_variable(key)-value)>1e-6:raise ValueError('Verified input mismatch: '+key)
    for key,value in plan['settings'].items():mc.set_variable(key,value)
    actual={key:mc.get_variable(key) for key in plan['settings']}
    if any(actual[k]!=value for k,value in plan['settings'].items()):raise ValueError('Small Signal setting readback mismatch')
    return actual


def worker(folder,probe=False):
    from low_voltage import start,parse_csv
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    for key,hash_key in (('source_model','model_sha256'),('source_database','database_sha256'),('source_snapshot','snapshot_sha256')):
        if sha(plan[key])!=plan[hash_key]:raise ValueError('Frozen source changed: '+key)
    work=folder/('probe' if probe else 'case');work.mkdir();mc=None;started=time.time()
    try:
        model=work/'small_signal.mot';db=work/'working_materials.mdb'
        shutil.copy2(plan['source_model'],model);shutil.copy2(plan['source_database'],db)
        mc,_=start();mc.load_from_file(str(model));mc.select_material_database(str(db),False)
        mc.clear_message_log();actual=configure(mc,plan)
        mc.save_to_file(str(model));write_json(work/'readback.json',actual)
        if probe:
            write_json(folder/'capability_probe.json',{'status':'settings_supported','readback':actual,
                       'native_fea_calls':0,'semantics_qualified':False,'elapsed_s':time.time()-started})
            return
        write_json(work/'progress.json',{'phase':'solving_inductance','started_unix':started})
        t=time.perf_counter();mc.do_magnetic_calculation();solver_s=time.perf_counter()-t
        if any(mc.get_variable(k)!=v for k,v in plan['settings'].items()):raise ValueError('Settings changed during calculation')
        csv=work/'small_signal.csv';mc.export_results('EMagnetic',str(csv));values,_=parse_csv(csv)
        graphs={}
        for name in GRAPH_NAMES:
            try:
                x,y=mc.get_magnetic_graph(name)
                graphs[name]={'x':list(map(float,x)),'y':list(map(float,y)),
                              'units_status':'Native graph units require explicit verification before SI matrix assembly'}
            except Exception as exc:graphs[name]={'error':str(exc)}
        mc.save_to_file(str(model))
        write_json(folder/'result.json',{'status':'completed','analysis_kind':'small_signal_inductance',
            'candidate_id':plan['candidate_id'],'values':values,'graphs':graphs,
            'available_graphs':sum(bool(g.get('x')) for g in graphs.values()),
            'solver_s':solver_s,'elapsed_s':time.time()-started,'readback':actual,
            'mapping_qualified':False,'pwm_ripple_certified':False,
            'next_action':'validate_graph_names_units_and_matrix_before_PWM_use'})
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()


def supervise(folder):
    import msvcrt
    from run_spm_ripple_recovery import stop_owned
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    if (folder/'progress.json').exists():raise ValueError('Experiment already started')
    started=time.time();child=None
    lock=(ROOT/'motorcad_execution.lock').open('a+b')
    def progress(status,**extra):write_json(folder/'progress.json',{'status':status,'started_unix':started,
        'elapsed_s':time.time()-started,'planned_fea':1,'completed_fea':int(status=='completed'),**extra})
    try:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        progress('running')
        with (folder/'worker.log').open('wb') as log:
            child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker','--output',str(folder)],
                cwd=ROOT.parent,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            write_json(folder/'child.json',{'pid':child.pid})
            try:code=child.wait(timeout=plan['case_timeout_s'])
            except subprocess.TimeoutExpired:stop_owned(child);raise RuntimeError('Small Signal timeout')
        if code!=0 or not (folder/'result.json').is_file():raise RuntimeError('Small Signal worker failed; inspect worker.log')
        progress('completed')
    except BaseException as exc:
        if child and child.poll() is None:stop_owned(child)
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('failed',failed_cases=1)
        raise
    finally:lock.close()


def launch(folder):
    folder=Path(folder).resolve()
    if (folder/'progress.json').exists() or (folder/'launch.json').exists():raise ValueError('Already launched')
    plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    probe_path=folder/'capability_probe.json'
    probe=json.loads(probe_path.read_text(encoding='utf-8')) if probe_path.is_file() else {}
    if probe.get('status')!='settings_supported' or probe.get('readback')!=plan['settings']:
        raise ValueError('Matching Native settings probe required before FEA')
    with (folder/'supervisor.log').open('wb') as log:
        p=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'supervise','--output',str(folder)],
                           cwd=ROOT.parent,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    record={'supervisor_pid':p.pid,'waited_for_completion':False,'planned_fea':1}
    write_json(folder/'launch.json',record);return record


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','probe','start','worker','supervise'])
    p.add_argument('--output',required=True);p.add_argument('--source');a=p.parse_args()
    if a.command=='prepare':print(json.dumps(prepare(a.source,a.output),indent=2))
    elif a.command=='probe':worker(a.output,True)
    elif a.command=='start':print(json.dumps(launch(a.output)))
    elif a.command=='worker':worker(a.output)
    else:supervise(a.output)
