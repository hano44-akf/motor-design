"""Stage 2: verify selected formula candidates only; do not re-optimize geometry."""
from pathlib import Path
import argparse
import contextlib
import json
import math
import statistics
import time
import traceback
import copy
import low_voltage as solver
from study_io import write_json,export_job
from model_capabilities import validate_for_model as validate
from run_assessment import assess_run,normalized_shortfall,deficit_summary
from evaluation_policy import VOLTAGE_RESERVE_FACTOR,TORQUE_MATCH_RELATIVE_TOLERANCE,TORQUE_MATCH_TARGET_FACTOR,correction_factor,snapshot as evaluation_policy_snapshot
from operating_control import control_policy,control_from_run
from motorcad_open import selected_model,queue_open
from result_policy import candidate_rank
from controller_limits import current_ripple_limit,torque_ripple_limit
from flux_limits import flux_density_limit
from verification_conditions import condition_plan,coverage,capacity_partner

ROOT=Path(__file__).resolve().parent


def verification_estimate(formula,selected_ids):
    selected=[c for c in formula['results'] if c['id'] in selected_ids]
    if not selected or len(selected)!=len(set(selected_ids)):raise ValueError('Select saved formula candidates to verify')
    request=formula['request'];plan=condition_plan(request);conditions=len(plan)
    times=[]
    for path in (ROOT/'jobs/20261022_132138').glob('*.json'):
        if '_final_' not in path.name and 'precision_correction' not in path.name:continue
        record=json.loads(path.read_text(encoding='utf-8'))
        if record.get('resolution_points',0)>=120 and record.get('timings',{}).get('total_s',0)>0:times.append(record['timings']['total_s'])
    seconds=statistics.median(times) if times else None
    count=len(selected)*conditions
    return {'models':len(selected),'conditions_per_model':conditions,'base_solves':count,'max_solves_with_corrections':count*3,
            'nominal_conditions_per_model':sum(p['role']=='nominal' for p in plan),
            'capacity_conditions_per_model':sum(p['role']=='capacity' for p in plan),
            'seconds_per_solve':seconds,'estimated_min_s':count*seconds if seconds else None,
            'estimated_max_s':count*3*seconds if seconds else None,'timing_samples':len(times),
            'scope':'Historical 120-point solve/setup/export median; excludes application/material startup, retries and queueing; up to 2 torque corrections per condition'}


def run_verification(request,folder):
    import msvcrt
    request=validate(request);folder=Path(folder).resolve();source=ROOT/'jobs'/request['formula_source_job']
    formula=json.loads((source/'result.json').read_text(encoding='utf-8'))
    selected=[c for c in formula['results'] if c['id'] in request['selected_model_ids']]
    if not selected or len(selected)!=len(set(request['selected_model_ids'])):raise ValueError('Invalid model selection')
    policy=control_policy(request);op=request['operating_point'];solver.OUT=folder
    start=time.perf_counter();started=time.time();mc=None;engine_lock=None;solves=0;results=[];completed=False
    def progress(status,**extra):
        write_json(folder/'progress.json',{'status':status,'started_unix':started,'elapsed_s':time.perf_counter()-start,
            'solves_this_session':solves,'selected_models':len(selected),'completed_models':len(results),**extra})
    def solve(label,design,bus,temp,condition):
        nonlocal solves
        if (folder/'cancel.request').exists():raise InterruptedError('Stopped after current solve')
        progress('solving',label=label)
        options={**request['spm'],'speed_rpm':op['speed_rpm'],'temperature_C':temp,
                 'connection':'delta','strands':1,'paths':1,'phase_advance_deg':design.get('phase_advance_deg',0)}
        row=solver.solve(mc,label,design['diameter_mm'],design['length_mm'],design['turns_per_coil'],
            design['wire_diameter_mm'],design['input_peak_current_A'],bus,120,options=options,geometry=design.get('geometry_mm'))
        solves+=1
        expected={'Stator Lam (Back Iron)':request['core'],'Stator Lam (Tooth)':request['core'],'Rotor Lam (Back Iron)':request['core'],'Magnet':request['magnet']}
        if row.get('component_materials')!=expected:raise RuntimeError('Selected model material readback differs from request')
        row['design']={**design,'voltage_V':bus};row['resolution_points']=120
        row.update(verification_role=condition['role'],condition_id=condition['condition_id'],target_torque_Nm=condition['target_torque_Nm'])
        if design.get('control_prediction'):row['operating_control']=design['control_prediction']
        row['assessment']=assess_run(row,request);write_json(folder/(label+'.json'),row)
        return row
    try:
        engine_lock=(ROOT/'motorcad_execution.lock').open('a+b')
        if engine_lock.tell()==0:engine_lock.write(b'0');engine_lock.flush()
        engine_lock.seek(0)
        try:msvcrt.locking(engine_lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError('Motor-CAD is busy in another worker; no solver instance was started. Retry after that worker finishes.') from exc
        progress('starting');mc,launch=solver.start();progress('preparing_materials');solver.prepare(mc,request['core'],request['magnet'])
        for model in selected:
            c={**model,'formula_design':model['design'],'runs':[]};reference=None
            for condition in condition_plan(request):
                ti=condition['temperature_index'];vi=condition['voltage_index'];temp=condition['temperature_C'];bus=condition['voltage_V']
                target=condition['target_torque_Nm'];role=condition['role']
                point_request=copy.deepcopy(request);point_request['operating_point']['torque_Nm']=target
                design=dict(model['design'])
                design['input_peak_current_A']*=target/op['torque_Nm']
                if role=='capacity':design.pop('control_prediction',None)
                if reference and (policy['current_control']!='ID0' or policy['field_weakening']):
                    cp=control_from_run(reference,point_request,bus,temp)
                    design.update(input_peak_current_A=cp['phase_peak_A']*math.sqrt(3),phase_advance_deg=cp['phase_advance_deg'],control_prediction=cp)
                row=solve(f"{c['id']}_final_{role}_t{ti}_v{vi}",design,bus,temp,condition)
                for correction in range(2):
                    torque=row['values']['Shaft Torque']
                    if target<=torque<=target*(1+TORQUE_MATCH_RELATIVE_TOLERANCE):break
                    if torque<=0:break
                    if policy['current_control']!='ID0' or policy['field_weakening']:
                        cp=control_from_run(row,point_request,bus,temp)
                        design={**design,'input_peak_current_A':cp['phase_peak_A']*math.sqrt(3),
                                'phase_advance_deg':cp['phase_advance_deg'],'control_prediction':cp}
                    else:design={**design,'input_peak_current_A':design['input_peak_current_A']*correction_factor(torque,target)}
                    row=solve(f"{c['id']}_final_{role}_t{ti}_v{vi}_correction{correction}",design,bus,temp,condition)
                if reference is None:reference=row
                c['runs'].append(row)
            c['condition_coverage']=coverage(c['runs'],request)
            for row in c['runs']:
                row['assessment']=assess_run(row,request,capacity_partner(row,c['runs'],request))
                write_json(folder/(row['label']+'.json'),row)
            c['design']={k:v for k,v in c['runs'][0]['design'].items() if k!='voltage_V'}
            for key in ('physical_screens_pass','known_targets_met','target_met','requirements_fully_verified'):
                c[key]=c['condition_coverage']['complete'] and all(row['assessment'][key] for row in c['runs'])
            c['worst_efficiency_pct']=min(row['values']['System Efficiency'] for row in c['runs'] if row['verification_role']=='nominal')
            c['worst_capacity_efficiency_pct']=min((row['values']['System Efficiency'] for row in c['runs'] if row['verification_role']=='capacity'),default=None)
            c['worst_normalized_shortfall']=max(normalized_shortfall(row,request) for row in c['runs'])
            c['deficit_reviews']=[deficit_summary(row,request) for row in c['runs']]
            c['provisional_rank']=candidate_rank([row['assessment'] for row in c['runs']],c['deficit_reviews'])
            c['has_known_requirement_violation']=any(row['assessment']['requirement_summary']['violated'] for row in c['runs'])
            results.append(c);progress('model_completed',model_id=c['id'])
        valid=[c for c in results if c['physical_screens_pass']]
        best=min(valid,key=lambda c:(not c['target_met'],c['provisional_rank'])) if valid else None
        recorded=[json.loads(p.read_text(encoding='utf-8')) for p in folder.glob('*.json') if '_final_' in p.name]
        result={'schema':'spm-job-result-v1','stage':'verification','status':'target_met' if any(c['target_met'] for c in results)
            else 'verification_incomplete' if any(not c['has_known_requirement_violation'] for c in valid) else 'best_effort' if valid else 'no_screened_candidate',
            'request':request,'results':results,'best_available':best['id'] if best else None,
            'source_formula_job':request['formula_source_job'],'search_statistics':formula['search_statistics'],
            'effective_airgap_bounds_mm':formula['effective_airgap_bounds_mm'],'operating_policy':policy,
            'effective_flux_density_max_T':flux_density_limit(request.get('flux_density_max_T')),
            'effective_pwm_current_ripple_max_pct':current_ripple_limit(request.get('pwm_current_ripple_max_pct')),
            'effective_torque_ripple_limit_pct':op.get('torque_ripple_max_pct') if op.get('torque_ripple_max_pct') is not None else 20,
            'timings':{'session_wall_s':time.perf_counter()-start,'launch_s':launch,'optimization_compute_s':formula['timings']['optimization_compute_s'],
                'final_solver_sum_s':sum(row['timings']['solver_s'] for c in results for row in c['runs']),
                'all_recorded_solver_s':sum(row['timings']['solver_s'] for row in recorded),'recorded_solve_count':solves},
            'verification_estimate':verification_estimate({**formula,'request':request},request['selected_model_ids']),
            'limitations':['Selected geometry only; current/angle may be corrected at each condition.',
                'Positive torque margin adds a separate capacity point at every temperature/bus. All existing limits apply to both roles; worst_efficiency_pct reports nominal points only.',
                'Prescribed-current FEA does not validate PWM, saturated MTPA optimality or demagnetization. Thermal and structural analyses excluded by user.']}
        result['evaluation_policy']=evaluation_policy_snapshot();write_json(folder/'result.json',result);export_job(folder,result);completed=True;progress('completed',models=len(results))
        return result
    except BaseException as exc:
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('cancelled' if isinstance(exc,InterruptedError) else 'failed',error=str(exc));raise
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        if engine_lock:engine_lock.close()
        if completed and request.get('open_motorcad_after') and results:
            try:queue_open(folder,best['id'] if best else results[0]['id'])
            except Exception as exc:write_json(folder/'motorcad_open_error.json',{'error':str(exc)})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--job',type=Path,required=True);args=parser.parse_args()
    run_verification(json.loads((args.job/'request.json').read_text(encoding='utf-8')),args.job)
