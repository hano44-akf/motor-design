"""Persisted, sequential native batch. Launch detached; inspect progress later.

No automatic solver retry. Subprocess isolation bounds a stalled phase; timed-out
native instances are reported for review and are never killed by process name.
"""
import argparse
import copy
import contextlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import traceback
from datetime import datetime,timezone
from study_io import write_json

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent


def controls_differ(a,b):
    return any(abs(a[k]-b[k])>1e-5 for k in ('phase_peak_A','phase_advance_deg'))


def diagnostics(source,folder):
    import msvcrt
    import low_voltage as solver
    from motorcad_adapter import apply_checked
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True)
    reference=json.loads(Path(source).read_text(encoding='utf-8'))
    design=reference['design'];geometry=reference['geometry_mm'];options=reference['input_options']
    solver.OUT=folder;mc=None;handle=None;rows=[];failures=[];start=time.perf_counter()
    try:
        handle=(ROOT/'motorcad_execution.lock').open('a+b')
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        write_json(folder/'progress.json',{'status':'starting','solves_completed':0})
        mc,_=solver.start()
        materials=reference['component_materials']
        solver.prepare(mc,materials['Stator Lam (Back Iron)'],materials['Magnet'])
        # Same geometry/turns/current as the saved paired 20 C reference.
        opt={**options,'phase_advance_deg':0,'speed_rpm':reference['values']['Shaft Speed']}
        current=design['input_peak_current_A'];bus=design['voltage_V']
        g={k:v for k,v in geometry.items() if k not in ('Shaft_Dia_[F]','Shaft_Dia_[R]')}
        specs=[]
        for scale in (0,.25,.5,1,1.5):specs.append((f'current_{str(scale).replace(".","p")}',current*scale,0,120,scale==0))
        for angle in (-30,-15,15,30):specs.append((f'angle_{angle}',current,angle,120,False))
        for points in (60,240,360):specs.append((f'resolution_{points}',current,0,points,False))
        for label,amps,angle,points,cogging in specs:
            if (folder.parent/'cancel.request').exists():raise InterruptedError('Batch stop requested')
            write_json(folder/'progress.json',{'status':'solving','label':label,'solves_completed':len(rows),'elapsed_s':time.perf_counter()-start})
            try:
                row=solver.solve(mc,label,design['diameter_mm'],design['length_mm'],design['turns_per_coil'],
                    design['wire_diameter_mm'],amps,bus,points,
                    options={**opt,'phase_advance_deg':angle},geometry=g,
                    calculation_settings={'CoggingTorqueCalculation':cogging,'TorqueNumberCycles':2,'BackEMFNumberCycles':2})
                if row['component_materials']!=materials:raise RuntimeError('Diagnostic material assignment mismatch')
                rows.append({'label':label,'current_line_peak_A':amps,'phase_advance_deg':angle,'points_per_electrical_cycle':points,
                    'torque_Nm':row['values'].get('Shaft Torque'),'mean_electromagnetic_torque_Nm':row['values'].get('Average Torque (MsVw)'),
                    'torque_ripple_pct':None if amps==0 else row['values'].get('Torque Ripple (MsVw) [%]'),
                    'solver_s':row['timings']['solver_s'],'output':str(folder/(label+'.json'))})
                # Snapshot is the native winding definition, not a certified
                # match to the synthesized winding; retain for later comparison.
                if label=='current_1':
                    try:mc.save_winding_pattern(str(folder/'native_winding.txt'))
                    except Exception as exc:failures.append({'label':'winding_export','error':str(exc)})
            except Exception as exc:
                failures.append({'label':label,'error':str(exc),'traceback':traceback.format_exc()})
                # Do not continue issuing calculations against an uncertain app.
                break
            write_json(folder/'partial_results.json',{'runs':rows,'failures':failures})
        result={'status':'completed' if not failures else 'completed_with_errors','runs':rows,'failures':failures,
            'elapsed_s':time.perf_counter()-start,
            'limitations':['Angular resolution comparison only; mesh refinement is still pending.',
                'No PWM/circuit, thermal, structural or frozen-permeability decomposition.',
                'Native winding export requires subsequent slot-by-slot comparison; not automatically certified.',
                'No independent DOE model validation; this is current/angle diagnostic evidence.']}
        write_json(folder/'result.json',result);write_json(folder/'progress.json',{'status':result['status'],'solves_completed':len(rows)})
        if failures:raise RuntimeError('Diagnostic phase has errors; see result.json')
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        if handle:handle.close()


def run_batch(folder):
    from operating_control import control_from_run
    folder=Path(folder).resolve();manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    start=time.time();events=[];completed=[];errors=[];reviews=[]
    def progress(status,**extra):
        write_json(folder/'progress.json',{'status':status,'started_unix':start,'elapsed_s':time.time()-start,
            'completed_phases':completed,'errors':errors,'events':events[-100:],**extra})
    def child(label,command):
        if (folder/'cancel.request').exists():raise InterruptedError('Batch stop requested')
        events.append({'label':label,'started_unix':time.time()});progress('running',active_phase=label)
        with (folder/(label+'.log')).open('ab') as log:
            process=subprocess.Popen([sys.executable,*command],cwd=PROJECT,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            write_json(folder/'active_child.json',{'pid':process.pid,'label':label,'command':command})
            try:code=process.wait(timeout=manifest['phase_timeout_s'])
            except subprocess.TimeoutExpired:
                process.terminate();process.wait(timeout=30)
                raise RuntimeError('Phase timeout; review any native instance before restarting: '+label)
        if code:errors.append({'phase':label,'exit_code':code});progress('running',active_phase=None);return False
        completed.append(label);return True
    def verify_job(label,source_id,request,selected):
        job=f"{manifest['job_prefix']}_{time.time_ns()%1000000000}"
        out=ROOT/'jobs'/job;out.mkdir()
        request=copy.deepcopy(request);request.update(formula_source_job=source_id,selected_model_ids=selected,open_motorcad_after=False)
        write_json(out/'request.json',request)
        write_json(folder/(label+'_job.json'),{'job_id':job,'folder':str(out)})
        okay=child(label,[str(ROOT/'verify_formula_job.py'),'--job',str(out)])
        return json.loads((out/'result.json').read_text(encoding='utf-8')) if okay else None
    try:
        prior=manifest.get('wait_for_batch')
        if prior:
            while True:
                previous=json.loads((Path(prior)/'progress.json').read_text(encoding='utf-8'))
                if previous['status'] in ('completed','completed_with_errors','failed','cancelled'):
                    if previous['status'] in ('failed','cancelled'):raise RuntimeError('Predecessor did not finish safely; review before recovery')
                    if any(e.get('phase') not in manifest.get('allowed_predecessor_errors',[]) for e in previous.get('errors',[])):
                        raise RuntimeError('Unexpected predecessor failure; recovery held for review')
                    break
                if time.time()-start>7200:raise RuntimeError('Predecessor batch wait timed out')
                progress('waiting_for_predecessor',predecessor=prior)
                time.sleep(5)
        progress('running')
        for item in manifest['sources']:
            source_id=item['formula_job'];formula=json.loads((ROOT/'jobs'/source_id/'result.json').read_text(encoding='utf-8'))
            request=copy.deepcopy(formula['request']);op=request['operating_point'];buses=sorted(set(op['voltages_V']))
            request['operating_point']['voltages_V']=[buses[0]]
            result=verify_job(item['id']+'_minimum_voltage',source_id,request,[m['id'] for m in formula['results']])
            if result:
                for model in result['results']:
                    reference=model['runs'][0]
                    for bus in buses[1:]:
                        source_bus=reference['design']['voltage_V']
                        base=control_from_run(reference,formula['request'],source_bus,20)
                        target=control_from_run(reference,formula['request'],bus,20)
                        review={'shape':item['id'],'model':model['id'],'source_bus_V':source_bus,'bus_V':bus,
                            'control_at_source':base,'control_at_target':target,
                            'scope':'Prescribed-current electromagnetic point only; bus-dependent inverter/DC input losses not validated by reuse.'}
                        if controls_differ(base,target):
                            # New prescribed current point; use an explicitly
                            # forked saved candidate with identical geometry.
                            fork_id=f"{manifest['job_prefix']}_{time.time_ns()%1000000000}"
                            fork=ROOT/'jobs'/fork_id;fork.mkdir()
                            f=copy.deepcopy(formula);m=next(m for m in f['results'] if m['id']==model['id'])
                            m['design'].update(input_peak_current_A=target['phase_peak_A']*math.sqrt(3),
                                phase_advance_deg=target['phase_advance_deg'],control_prediction=target)
                            f['batch_control_seed_source']=source_id
                            write_json(fork/'result.json',f)
                            req=copy.deepcopy(formula['request']);req['operating_point']['voltages_V']=[bus]
                            extra=verify_job(f"{item['id']}_{model['id']}_{bus:g}V",fork_id,req,[model['id']])
                            if extra:
                                reference=extra['results'][0]['runs'][0];review['status']='additional_fea_completed'
                            else:review['status']='additional_fea_failed'
                        else:review['status']='same_electromagnetic_control_point_no_additional_fea'
                        reviews.append(review);write_json(folder/'voltage_reviews.json',reviews)
            if item.get('diagnostics',True):
                calibration=ROOT/item['calibration']
                child(item['id']+'_diagnostics',[str(Path(__file__).resolve()),'--diagnostic-source',str(calibration),
                    '--output',str(folder/(item['id']+'_diagnostics'))])
        write_json(folder/'summary.json',{'status':'completed_with_errors' if errors else 'completed',
            'completed_phases':completed,'errors':errors,'voltage_reviews':reviews,'wall_s':time.time()-start,
            'scope':'Ready 4p/12s surface models only; other topologies and mesh/DOE/PWM/demagnetization remain pending. Thermal and structural analyses excluded by user.'})
        progress('completed_with_errors' if errors else 'completed',active_phase=None)
    except BaseException as exc:
        errors.append({'error':str(exc),'traceback':traceback.format_exc()})
        progress('cancelled' if isinstance(exc,InterruptedError) else 'failed',active_phase=None)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--batch',type=Path)
    parser.add_argument('--diagnostic-source',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.batch:run_batch(args.batch)
    elif args.diagnostic_source and args.output:diagnostics(args.diagnostic_source,args.output)
    else:parser.error('Expected batch or diagnostic source/output')
