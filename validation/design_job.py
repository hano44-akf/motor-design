"""AI-free SPM study runner. Explicitly scoped to a 4-pole/12-slot delta family.

python validation/design_job.py --request validation/requests/low_voltage.json
python validation/design_job.py --resume validation/jobs/<job-directory>
"""
from pathlib import Path
import argparse
import contextlib
import csv
import hashlib
import io
import json
import math
import shutil
import time
import traceback
import low_voltage as solver
from motorcad_adapter import variables
from optimize_low_voltage import optimize
from export_csv import clean, cell, flatten
from controller_limits import pole_limit,inductance_voltage_upper,torque_ripple_limit,current_ripple_limit,current_ripple_review
from flux_limits import flux_density_limit,flux_density_review
from dimension_grid import mm,wire_outer,grid_bounds
from evaluation_policy import VOLTAGE_RESERVE_FACTOR,TORQUE_MATCH_RELATIVE_TOLERANCE,TORQUE_MATCH_TARGET_FACTOR,correction_factor,snapshot as evaluation_policy_snapshot
from operating_control import control_policy,airgap_bounds,control_from_run
from rotor_catalog import require_execution

ROOT=Path(__file__).resolve().parent

# Compatibility re-exports for historical scripts and saved-job tooling.
from study_io import write_json,export_job
from model_capabilities import validate_for_model as validate
from run_assessment import assess_run,normalized_shortfall


def run_job(request,folder,resume=False):
    request=validate(request);folder=folder.resolve();folder.mkdir(parents=True,exist_ok=True)
    original=folder/'request.json'
    if original.exists() and validate(json.loads(original.read_text(encoding='utf-8')))!=request:raise ValueError('Resume request differs')
    write_json(original,request);solver.OUT=folder
    if resume and (folder/'cancel.request').exists():(folder/'cancel.request').unlink()
    if (folder/'error.json').exists():
        history=folder/'history';history.mkdir(exist_ok=True)
        (folder/'error.json').replace(history/f'error_{time.time_ns()}.json')
    began=time.perf_counter();mc=None;solves=0;events=[];op=request['operating_point'];all_candidates=[];engine_lock=None;completed=False
    policy=control_policy(request)
    new_options='airgap_bounds_mm' in request or not resume or 'current_control' in op or 'field_weakening' in op
    gap_range=airgap_bounds(request) if new_options else None
    def controlled_design(design,run,bus,temp):
        if policy['current_control']=='ID0' and not policy['field_weakening']:return design
        prediction=control_from_run(run,request,bus,temp)
        return {**design,'input_peak_current_A':prediction['phase_peak_A']*math.sqrt(3),
                'phase_advance_deg':prediction['phase_advance_deg'],'control_prediction':prediction}
    def progress(stage,**extra):
        event={'stage':stage,'elapsed_s':time.perf_counter()-began,**extra};events.append(event)
        write_json(folder/'progress.json',{'status':stage,'solves_this_session':solves,'events':events[-150:],**extra})
        print(json.dumps(event,ensure_ascii=False),flush=True)
    def cancelled():
        if (folder/'cancel.request').exists():raise InterruptedError('Stopped by user; completed solves retained')
    def calculate(label,design,voltage,temp,points=60):
        nonlocal solves,mc
        cancelled();path=folder/(label+'.json')
        options={**request['spm'],'speed_rpm':op['speed_rpm'],'temperature_C':temp,'connection':'delta','strands':1,'paths':1,'magnet_arc_deg':design.get('magnet_arc_deg',120)}
        if new_options or 'phase_advance_deg' in design:options['phase_advance_deg']=design.get('phase_advance_deg',0.)
        if resume and path.exists():
            cached=json.loads(path.read_text(encoding='utf-8'))
            old_points=cached.get('resolution_points',120 if '_final_' in label else 60)
            if cached['design']=={**design,'voltage_V':voltage} and cached.get('input_options')==options and old_points==points:
                cached['assessment']=assess_run(cached,request)
                write_json(path,cached)
                return cached
            archive=folder/'history';archive.mkdir(exist_ok=True)
            stamp=hashlib.sha256(path.read_bytes()).hexdigest()[:10]
            for ext in ['.json','.csv','.mot']:
                source=folder/(label+ext)
                if source.exists():shutil.copy2(source,archive/(label+'_'+stamp+ext))
        progress('solving',label=label)
        for attempt in range(2):
            attempt_started=time.perf_counter()
            try:
                r=solver.solve(mc,label,design['diameter_mm'],design['length_mm'],design['turns_per_coil'],design['wire_diameter_mm'],design['input_peak_current_A'],voltage,points,options=options,geometry=design.get('geometry_mm'))
                break
            except Exception as exc:
                log=folder/'solver_retries.json'
                records=json.loads(log.read_text(encoding='utf-8')) if log.exists() else []
                records.append({'label':label,'attempt':attempt+1,'failed_attempt_wall_s':time.perf_counter()-attempt_started,'error':str(exc)})
                write_json(log,records)
                # Retry transport/native application faults, never geometry/mapping errors.
                if attempt or not any(token in str(exc) for token in ['RPC','Access violation','Connection']):raise
                progress('reconnecting_motorcad',label=label)
                with contextlib.suppress(Exception):mc.quit()
                mc,_=solver.start()
        if 'magnet_arc_deg' in design:r['design']['magnet_arc_deg']=design['magnet_arc_deg']
        for key in ('airgap_mm','phase_advance_deg','control_prediction'):
            if key in design:r['design'][key]=design[key]
        if 'control_prediction' in design:r['operating_control']=design['control_prediction']
        solves+=1
        expected={'Stator Lam (Back Iron)':request['core'],'Stator Lam (Tooth)':request['core'],'Rotor Lam (Back Iron)':request['core'],'Magnet':request['magnet']}
        if r['component_materials']!=expected:raise RuntimeError('Material readback changed')
        r['resolution_points']=points;r['assessment']=assess_run(r,request);write_json(path,r)
        return r
    try:
        import msvcrt
        engine_lock=(ROOT/'motorcad_execution.lock').open('a+b')
        if engine_lock.tell()==0:engine_lock.write(b'0');engine_lock.flush()
        engine_lock.seek(0)
        try:msvcrt.locking(engine_lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise RuntimeError('Another Python design worker is already using Motor-CAD')
        progress('starting');mc,launch=solver.start()
        if not (resume and (folder/'material_seed.mot').exists()):
            progress('preparing_materials');solver.prepare(mc,request['core'],request['magnet'])
        base={'diameter_mm':85,'length_mm':20,'turns_per_coil':6,'wire_diameter_mm':1.8,'input_peak_current_A':40}
        if gap_range:
            base.update(airgap_mm=mm(sum(gap_range)/2),geometry_mm={'Airgap':mm(sum(gap_range)/2)},phase_advance_deg=0.)
        calibration=calculate('calibration',base,min(op['voltages_V']),request['temperatures_C'][0])
        calibration_file='calibration.json';seen=set()
        for round_index in range(request.get('search_rounds',2)):
            cancelled();progress('optimizing',round=round_index+1)
            with contextlib.redirect_stdout(io.StringIO()):
                prediction=optimize(calibration_file=calibration_file,suffix=f'_round{round_index}',efficiency_target=op.get('efficiency_min_pct'),dc_voltage=min(op['voltages_V']),torque_target=op['torque_Nm'],speed_rpm=op['speed_rpm'],search_bounds=request.get('bounds'),output_dir=folder,switching_frequency_hz=request.get('switching_frequency_hz'),airgap_bounds_mm=gap_range,current_control=policy['current_control'],field_weakening=policy['field_weakening'],current_density_max_A_mm2=op.get('current_density_max_A_mm2'),dc_current_max_A=op.get('dc_current_max_A'))
            round_results=[]
            for index,p in enumerate(prediction['predictions']):
                if not p['physical_screen_pass']:continue
                design={'diameter_mm':mm(p['diameter_mm']),'length_mm':mm(p['length_mm']),'turns_per_coil':p['turns_per_coil'],'wire_diameter_mm':p['wire_diameter_mm'],'input_peak_current_A':p['line_peak_A']}
                if 'airgap_mm' in p:design.update(airgap_mm=p['airgap_mm'],geometry_mm={'Airgap':p['airgap_mm']})
                if p.get('operating_control'):
                    design.update(phase_advance_deg=p['operating_control']['phase_advance_deg'],control_prediction=p['operating_control'])
                # Rounding a boundary solution upward must not put the wire
                # outside the slot opening. Stay inside the user's wire bounds.
                design['wire_diameter_mm']=min(design['wire_diameter_mm'],mm(mm(3*design['diameter_mm']/130)-.1))
                if design['wire_diameter_mm']<request.get('bounds',[[55,100],[20,65],[1,8],[.8,2.2]])[3][0]:continue
                signature=tuple(design.get(k) for k in ('diameter_mm','length_mm','turns_per_coil','wire_diameter_mm','airgap_mm'))
                if signature in seen:continue
                seen.add(signature);trial_runs=[]
                for tune in range(5):
                    r=calculate(f'r{round_index}_{index}_tune{tune}',design,min(op['voltages_V']),request['temperatures_C'][0]);trial_runs.append(r)
                    t=r['values']['Shaft Torque'];peak=r['values']['Line-Line Terminal Voltage (peak)']
                    if r['assessment']['physical_screens_pass'] and t>=op['torque_Nm']:break
                    factor=correction_factor(max(t,.001),op['torque_Nm'])
                    if peak>min(op['voltages_V']):factor=min(factor,min(op['voltages_V'])/peak*VOLTAGE_RESERVE_FACTOR)
                    if abs(factor-1)<.001:break
                    design=controlled_design(design,r,min(op['voltages_V']),request['temperatures_C'][0]) if policy['current_control']!='ID0' or policy['field_weakening'] else {**design,'input_peak_current_A':design['input_peak_current_A']*factor}
                feasible=[r for r in trial_runs if r['assessment']['physical_screens_pass']]
                chosen=min(feasible or trial_runs,key=lambda r:normalized_shortfall(r,request))
                candidate={'id':f'R{round_index+1}-{index+1}','objective':p['objective'],'design':chosen['design'],'prediction':p,'tune_label':chosen['label'],'runs':[]}
                all_candidates.append(candidate);round_results.append(chosen)
                # Save checkpoint before the expensive final temperature/voltage grid.
                write_json(folder/'candidates.json',all_candidates)
            if round_results:
                best=max(round_results,key=lambda r:r['values']['System Efficiency'] if r['assessment']['physical_screens_pass'] else -1)
                calibration_file=best['label']+'.json'
            if len(all_candidates)>=3 and any(r['assessment']['target_met'] for r in round_results):break
        # Rank screened candidates before full validation. Keep up to three genuinely different geometries.
        def tune_rank(c):
            r=json.loads((folder/(c['tune_label']+'.json')).read_text(encoding='utf-8'));a=r['assessment']
            return (not a['physical_screens_pass'],not a['known_targets_met'],normalized_shortfall(r,request),-r['values']['System Efficiency'])
        representatives=sorted(all_candidates,key=tune_rank)[:3]
        if request.get('detailed_review'):
            from detailed_review import refine
            refine(representatives,request,folder,calculate,progress,normalized_shortfall)
        for index,c in enumerate(representatives):
            # Torque can shift when temporal resolution is increased. Correct with
            # high-resolution feedback rather than accepting a near-miss as a pass.
            first=calculate(f'{c["id"]}_final_t0_v0',c['design'],op['voltages_V'][0],request['temperatures_C'][0],120)
            for correction in range(2):
                torque=first['values']['Shaft Torque']
                if op['torque_Nm']<=torque<=op['torque_Nm']*(1+TORQUE_MATCH_RELATIVE_TOLERANCE) or not first['assessment']['physical_screens_pass']:break
                adjusted={**c['design'],'input_peak_current_A':c['design']['input_peak_current_A']*correction_factor(max(torque,.001),op['torque_Nm'])}
                adjusted=controlled_design(adjusted,first,op['voltages_V'][0],request['temperatures_C'][0])
                trial=calculate(f'{c["id"]}_precision_correction{correction}',adjusted,op['voltages_V'][0],request['temperatures_C'][0],120)
                if not trial['assessment']['physical_screens_pass']:break
                c['design']=adjusted;first=trial
            for ti,temp in enumerate(request['temperatures_C']):
                for vi,voltage in enumerate(op['voltages_V']):
                    per_condition=controlled_design(c['design'],first,voltage,temp)
                    r=first if ti==0 and vi==0 else calculate(f'{c["id"]}_final_t{ti}_v{vi}',per_condition,voltage,temp,120)
                    if ti!=0 or vi!=0:
                        for correction in range(2):
                            if op['torque_Nm']<=r['values']['Shaft Torque']<=op['torque_Nm']*(1+TORQUE_MATCH_RELATIVE_TOLERANCE):break
                            torque=r['values']['Shaft Torque']
                            if torque<=0:break
                            if policy['current_control']=='ID0' and not policy['field_weakening']:
                                factor=correction_factor(torque,op['torque_Nm'])
                                per_condition={**per_condition,'input_peak_current_A':per_condition['input_peak_current_A']*factor}
                            else:per_condition=controlled_design(per_condition,r,voltage,temp)
                            r=calculate(f'{c["id"]}_final_t{ti}_v{vi}_ctrl{correction}',per_condition,voltage,temp,120)
                    c['runs'].append(r)
            c['physical_screens_pass']=all(r['assessment']['physical_screens_pass'] for r in c['runs'])
            c['target_met']=all(r['assessment']['target_met'] for r in c['runs'])
            c['known_targets_met']=all(r['assessment']['known_targets_met'] for r in c['runs'])
            c['requirements_fully_verified']=all(r['assessment']['requirements_fully_verified'] for r in c['runs'])
            c['worst_efficiency_pct']=min(r['values']['System Efficiency'] for r in c['runs'])
            c['worst_normalized_shortfall']=max(normalized_shortfall(r,request) for r in c['runs'])
        preference=request.get('selection_priority','efficient')
        representatives.sort(key=lambda c:(not c['physical_screens_pass'],not c['target_met'],c['worst_normalized_shortfall'],c['objective']!=preference,-c['worst_efficiency_pct']))
        valid=[c for c in representatives if c['physical_screens_pass']]
        recorded_solves=[]
        for record_path in list(folder.glob('*.json'))+list((folder/'history').glob('*.json')):
            record=json.loads(record_path.read_text(encoding='utf-8'))
            if isinstance(record,dict) and 'values' in record and 'solver_s' in record.get('timings',{}):recorded_solves.append(record)
        result={'schema':'spm-job-result-v1','status':'target_met' if any(c['target_met'] for c in valid) else 'verification_incomplete' if any(c['known_targets_met'] for c in valid) else 'best_effort' if valid else 'no_screened_candidate',
                'controller_configuration':pole_limit(op['speed_rpm'],request.get('switching_frequency_hz'),4),
                'effective_torque_ripple_limit_pct':torque_ripple_limit(op.get('torque_ripple_max_pct')),
                'effective_pwm_current_ripple_max_pct':current_ripple_limit(request.get('pwm_current_ripple_max_pct')),
                'effective_flux_density_max_T':flux_density_limit(request.get('flux_density_max_T')),
                'dimension_resolution_mm':.1,
                'operating_policy':policy,'effective_airgap_bounds_mm':gap_range,
                'request':request,'results':representatives,'best_available':valid[0]['id'] if valid else None,
                'timings':{'session_wall_s':time.perf_counter()-began,'launch_s':launch,'final_solver_sum_s':sum(r['timings']['solver_s'] for c in representatives for r in c['runs']),
                           'all_recorded_solver_s':sum(r['timings']['solver_s'] for r in recorded_solves),'recorded_solve_count':len(recorded_solves),
                           'optimization_compute_s':sum(json.loads(p.read_text(encoding='utf-8'))['optimization_compute_s'] for p in folder.glob('optimization_round*.json'))},
                'limitations':['Best found within stated family/bounds/budget, not global maximum.','50PN470 iron loss outside manufacturer 50/60Hz data is extrapolated.','Uniform prescribed temperature, zero mechanical loss and ideal inverter efficiency.','Voltage screens are necessary checks; switching-circuit feasibility and delta circulating currents are not verified.']}
        sessions_file=folder/'execution_sessions.json'
        previous_sessions=json.loads(sessions_file.read_text(encoding='utf-8')) if sessions_file.exists() else []
        result['timings']['cumulative_program_wall_s']=sum(s['wall_s'] for s in previous_sessions)+time.perf_counter()-began
        result['evaluation_policy']=evaluation_policy_snapshot();write_json(folder/'result.json',result);export_job(folder,result);progress('completed',result_status=result['status'],models=len(representatives),best_available=result['best_available'])
        completed=True
        return result
    except BaseException as exc:
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('cancelled' if isinstance(exc,InterruptedError) else 'failed',error=str(exc));raise
    finally:
        sessions_file=folder/'execution_sessions.json'
        sessions=json.loads(sessions_file.read_text(encoding='utf-8')) if sessions_file.exists() else []
        sessions.append({'wall_s':time.perf_counter()-began,'solves_this_session':solves,'resumed':resume})
        write_json(sessions_file,sessions)
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        if engine_lock:engine_lock.close()
        if completed and request.get('open_motorcad_after') and (folder/'result.json').is_file():
            try:
                from motorcad_open import queue_open
                saved=json.loads((folder/'result.json').read_text(encoding='utf-8'))
                chosen=next((c for c in saved['results'] if c['id']==saved['best_available']),None)
                chosen=chosen or next(iter(saved['results']),None)
                if chosen:queue_open(folder,chosen['id'])
            except Exception as exc:write_json(folder/'motorcad_open_error.json',{'error':str(exc)})

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--request',type=Path);parser.add_argument('--resume',type=Path);args=parser.parse_args()
    if args.resume:run_job(json.loads((args.resume/'request.json').read_text(encoding='utf-8')),args.resume,resume=True)
    elif args.request:run_job(json.loads(args.request.read_text(encoding='utf-8')),ROOT/'jobs'/time.strftime('%Y%m%d_%H%M%S'))
    else:parser.error('--request or --resume is required')
