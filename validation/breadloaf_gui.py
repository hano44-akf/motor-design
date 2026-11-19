"""Persisted GUI jobs for the restricted Breadloaf development workflow."""
import json
import hashlib
import math
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from study_io import write_json

ROOT=Path(__file__).resolve().parent.parent
HOME=ROOT/'outputs/breadloaf_gui'
LOCK=threading.RLock()
LEGACY={'pilot-search':('search',ROOT/'outputs/breadloaf_shape_search_20261104'),
        'pilot-validation':('validation',ROOT/'outputs/breadloaf_shape_verification_20261104'),
        'pilot-feedback':('feedback',ROOT/'outputs/breadloaf_current_feedback_20261104'),
        'shaft-search':('search',ROOT/'outputs/breadloaf_shaft_search_20261105'),
        'shaft-validation':('validation',ROOT/'outputs/breadloaf_shaft_verification_20261105'),
        'fine-search':('search',ROOT/'outputs/breadloaf_fine_search_20261105'),
        'fine-validation':('validation',ROOT/'outputs/breadloaf_fine_verification_20261105')}
SEED=ROOT/'outputs/spm_ripple_recovery_20261103/surface_breadloaf_13_snapshot.json'
MODEL=ROOT/'outputs/spm_ripple_validation_v2_20261103_140824/surface_breadloaf_13.mot'


def read(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def locate(job):
    if job in LEGACY:
        kind,folder=LEGACY[job];return kind,folder,{'id':job,'title':'기존 Breadloaf 개발 결과','created':0}
    if not isinstance(job,str) or not re.fullmatch(r'bf_[0-9a-f]{16}',job):raise ValueError('Invalid Breadloaf job ID')
    meta=read(HOME/job/'metadata.json')
    if not meta:raise ValueError('Breadloaf job not found')
    return meta['kind'],HOME/job/'artifacts',meta


def create(kind,parent=None):
    job='bf_'+uuid.uuid4().hex[:16];folder=HOME/job;folder.mkdir(parents=True)
    meta={'id':job,'kind':kind,'parent':parent,'created':time.time(),'title':'Breadloaf '+kind}
    write_json(folder/'metadata.json',meta)
    return job,folder/'artifacts',meta


def detail(job):
    from dimension_grid import resolution_policy
    kind,folder,meta=locate(job);progress=read(folder/'progress.json',{})
    result=read(folder/'result.json',{});plan=read(folder/'plan.json',{})
    state=progress.get('status','completed' if result else 'prepared')
    if kind=='search' and not progress and not result and meta.get('pid'):state='running'
    if state in ('running','searching') and meta.get('pid'):
        import psutil
        if not psutil.pid_exists(meta['pid']):state='failed'
    if state in ('running','searching') and isinstance(progress.get('started_unix'),(int,float)):
        progress={**progress,'elapsed_s':max(0,time.time()-progress['started_unix'])}
    counts=None
    if kind!='search':
        planned=plan.get('planned_fea',len(plan.get('cases',[])))
        completed=progress.get('completed_fea',0);failed=progress.get('failed_cases',0)
        counts={'required':planned,'completed':completed,'failed':failed,
                'unresolved_required':max(0,planned-completed),'unattempted':max(0,planned-completed-failed)}
    rows=[]
    if kind=='search':
        for candidate in result.get('finalists',[]):
            last=candidate['levels'][-1]
            rows.append({'id':candidate['id'],'dimensions':candidate['dimensions'],
                'predicted_ripple_pct':last.get('ripple_pct'),'line_peak_A':last.get('line_peak_A'),
                'predicted_torque_Nm':last.get('mean_Nm'),'actual_ripple_pct':None,
                'torque_status':last.get('status'),'torque_shortfall_Nm':last.get('torque_shortfall_Nm')})
            rows[-1]['model_screens']=last.get('model_screens')
            rows[-1]['predicted_shaft_torque_Nm']=last.get('predicted_shaft_torque_Nm')
            rows[-1]['shaft_control_status']=last.get('shaft_control_status')
            rows[-1]['shaft_control_reason']=last.get('shaft_control_reason')
    else:
        outcomes={r['id']:r for r in result.get('outcomes',[])}
        for case in plan.get('cases',[]):
            r=outcomes.get(case['id'],{});v=r.get('values',{})
            snapshot=read(folder/(case['id']+'_snapshot.json'),{})
            rows.append({'id':case['id'],'predicted_ripple_pct':case['predicted_ripple_pct'],
                'line_peak_A':snapshot.get('line_peak_A'),'actual_ripple_pct':r.get('actual_ripple_pct'),
                'electromagnetic_torque_Nm':v.get('Average torque (MsVw)'),
                'shaft_torque_Nm':v.get('Shaft Torque'),'efficiency_pct':v.get('System Efficiency'),
                'acceptance':r.get('acceptance'),'status':r.get('status','pending'),
                'dimensions':{k:snapshot.get('expected_native',{}).get(k) for k in ('Slot_Opening','Magnet_Arc_[ED]','MagnetReduction')}})
    summary=read(folder/'workflow_review.json') or read(folder/'verification_review.json')
    if plan.get('request_contract'):
        from breadloaf_pwm_screen import reference as pwm_reference,evaluate as pwm_evaluate
        pwm_ref=pwm_reference()
        for row in rows:
            saved=read(folder/(row['id']+'_snapshot.json'))
            if saved:
                row['pwm_advisory']=pwm_evaluate(saved,row.get('line_peak_A'),plan['request_contract'],pwm_ref)
    experiment=None
    numerical_review=None
    flux_experiment=None
    direct_preview=None
    direct_numerical_review=None
    low_cost_comparison=None
    leakage_geometry=None
    detailed_slot_review=None
    conductor_coordinate_review=None
    continuous_packing_review=None
    whole_grid_packing_review=None
    selected_continuous_packing=None
    coil_coordinate_proposal=None
    end_routing_review=None
    route_adjustment_review=None
    route_conflict_review=None
    bundle_routing_review=None
    transition_routing_review=None
    clearance_refinement_review=None
    exp_folder=ROOT/'outputs/breadloaf_small_signal_20261105'
    exp_plan=read(exp_folder/'plan.json',{})
    if exp_plan.get('source_batch')==str(folder.resolve()):
        exp_progress=read(exp_folder/'progress.json',{});exp_result=read(exp_folder/'result.json',{})
        elapsed=exp_progress.get('elapsed_s')
        if exp_progress.get('status')=='running':elapsed=max(0,time.time()-exp_progress['started_unix'])
        experiment={'state':exp_progress.get('status','prepared'),'required':exp_plan['planned_fea'],
                    'completed':exp_progress.get('completed_fea',0),'elapsed_s':elapsed,
                    'estimated_duration_minutes':exp_plan['estimated_duration_minutes'],
                    'available_graphs':exp_result.get('available_graphs'),'pwm_ripple_certified':False}
        numerical_review=read(exp_folder/'pwm_reference_review.json')
        if numerical_review:
            preview_path=exp_folder/'pwm_preview.json'
            numerical_review={**numerical_review,'source_matches':preview_path.is_file() and
                hashlib.sha256(preview_path.read_bytes()).hexdigest()==numerical_review.get('source_preview_sha256')}
    flux_folder=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'
    flux_plan=read(flux_folder/'plan.json',{})
    if flux_plan.get('source_batch')==str(folder.resolve()):
        flux_progress=read(flux_folder/'progress.json',{});elapsed=flux_progress.get('elapsed_s')
        if flux_progress.get('status')=='running':elapsed=max(0,time.time()-flux_progress['started_unix'])
        prior=sum(read(ROOT/'outputs'/old/'progress.json',{}).get('completed_fea',0) for old in
                  ('breadloaf_phase_mapping_20261105','breadloaf_phase_mapping_v2_20261105','breadloaf_phase_mapping_v3_20261105','breadloaf_phase_mapping_v4_20261105'))
        reused=len(flux_plan.get('reused_outcomes',[]))
        flux_experiment={'state':flux_progress.get('status','prepared'),'required':flux_plan['planned_fea'],
            'completed':flux_progress.get('completed_fea',0),'data_validated_cases':flux_progress.get('data_validated_cases',0)+reused,
            'reused_cases':reused,'mapping_case_count':flux_plan.get('total_mapping_cases',6),
            'elapsed_s':elapsed,'prior_diagnostic_fea':prior-reused,'active_case':flux_progress.get('active_case'),
            'estimated_duration_minutes':flux_plan['estimated_duration_minutes'],
            'review':read(flux_folder/'mapping_review.json'),'pwm_ripple_certified':False}
        direct_preview=read(flux_folder/'pwm_preview.json')
        if direct_preview:
            direct_preview={**direct_preview,'source_matches':hashlib.sha256((flux_folder/'mapping_review.json').read_bytes()).hexdigest()==direct_preview.get('source_mapping_sha256')}
        direct_numerical_review=read(flux_folder/'pwm_reference_review.json')
        if direct_numerical_review:
            direct_numerical_review={**direct_numerical_review,'source_matches':direct_preview is not None and direct_preview['source_matches'] and
                hashlib.sha256((flux_folder/'pwm_preview.json').read_bytes()).hexdigest()==direct_numerical_review.get('source_preview_sha256')}
        low_cost_comparison=read(flux_folder/'low_cost_matrix_review.json')
        if low_cost_comparison:
            low_cost_comparison={**low_cost_comparison,'source_matches':
                hashlib.sha256((flux_folder/'mapping_review.json').read_bytes()).hexdigest()==low_cost_comparison.get('source_mapping_sha256') and
                (flux_folder/'pwm_preview.json').is_file() and hashlib.sha256((flux_folder/'pwm_preview.json').read_bytes()).hexdigest()==low_cost_comparison.get('source_preview_sha256') and
                bool(low_cost_comparison.get('source_files')) and all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in low_cost_comparison.get('source_files',{}).items())}
        leakage_geometry=read(flux_folder/'leakage_geometry_review.json')
        if leakage_geometry:
            leakage_geometry={**leakage_geometry,'source_matches':bool(leakage_geometry.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in leakage_geometry.get('source_files',{}).items())}
        detailed_slot_review=read(flux_folder/'detailed_slot_review.json')
        if detailed_slot_review:
            detailed_slot_review={**detailed_slot_review,'source_matches':bool(detailed_slot_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in detailed_slot_review.get('source_files',{}).items())}
        conductor_coordinate_review=read(flux_folder/'conductor_coordinate_review.json')
        if conductor_coordinate_review:
            conductor_coordinate_review={**conductor_coordinate_review,'source_matches':bool(conductor_coordinate_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in conductor_coordinate_review.get('source_files',{}).items())}
        continuous_packing_review=read(flux_folder/'continuous_packing_review.json')
        if continuous_packing_review:
            continuous_packing_review={**continuous_packing_review,'source_matches':bool(continuous_packing_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in continuous_packing_review.get('source_files',{}).items())}
        whole_grid_packing_review=read(flux_folder/'whole_grid_packing_review.json')
        if whole_grid_packing_review:
            whole_grid_packing_review={**whole_grid_packing_review,'source_matches':bool(whole_grid_packing_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in whole_grid_packing_review.get('source_files',{}).items())}
        selected_continuous_packing=read(flux_folder/'selected_continuous_packing.json')
        if selected_continuous_packing:
            selected_continuous_packing={**selected_continuous_packing,'source_matches':bool(selected_continuous_packing.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in selected_continuous_packing.get('source_files',{}).items())}
        coil_coordinate_proposal=read(flux_folder/'coil_coordinate_proposal.json')
        if coil_coordinate_proposal:
            coil_coordinate_proposal={**coil_coordinate_proposal,'source_matches':bool(coil_coordinate_proposal.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in coil_coordinate_proposal.get('source_files',{}).items())}
        end_routing_review=read(flux_folder/'end_routing_review.json')
        if end_routing_review:
            end_routing_review={**end_routing_review,'source_matches':bool(end_routing_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in end_routing_review.get('source_files',{}).items())}
        route_adjustment_review=read(flux_folder/'route_adjustment_review.json')
        if route_adjustment_review:
            route_adjustment_review={**route_adjustment_review,'source_matches':bool(route_adjustment_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in route_adjustment_review.get('source_files',{}).items())}
        route_conflict_review=read(flux_folder/'route_conflict_review.json')
        if route_conflict_review:
            route_conflict_review={**route_conflict_review,'source_matches':bool(route_conflict_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in route_conflict_review.get('source_files',{}).items())}
        bundle_routing_review=read(flux_folder/'bundle_routing_review.json')
        if bundle_routing_review:
            bundle_routing_review={**bundle_routing_review,'source_matches':bool(bundle_routing_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in bundle_routing_review.get('source_files',{}).items())}
        transition_routing_review=read(flux_folder/'transition_routing_review.json')
        if transition_routing_review:
            transition_routing_review={**transition_routing_review,'source_matches':bool(transition_routing_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in transition_routing_review.get('source_files',{}).items())}
        clearance_refinement_review=read(flux_folder/'clearance_refinement_review.json')
        if clearance_refinement_review:
            clearance_refinement_review={**clearance_refinement_review,'source_matches':bool(clearance_refinement_review.get('source_files')) and
                all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest()==digest for p,digest in clearance_refinement_review.get('source_files',{}).items())}
    return {**meta,'id':job,'kind':kind,'state':state,'progress':progress,'rows':rows,
        'statistics':{k:result.get(k) for k in ('elapsed_s','unique_candidates','optimizer_nfev')},
        'search_variables':plan.get('variables'),
        'free_variable_count':plan.get('free_variable_count'),
        'full_grid_combinations':plan.get('grid_combinations_before_geometry_screen'),
        'selection_status':result.get('selection_status'),
        'fea_counts':counts,
        'target_electromagnetic_torque_Nm':plan.get('target_electromagnetic_torque_Nm'),
        'estimated_duration_minutes':plan.get('estimated_duration_minutes'),
        'summary':summary,'operating_comparison':read(folder/'operating_comparison.json'),
        'remaining_drive_review':read(folder/'remaining_drive_review.json'),
        'inductance_experiment':experiment,
        'pwm_preview':read(exp_folder/'pwm_preview.json') if experiment else None,
        'pwm_numerical_review':numerical_review,
        'flux_mapping_experiment':flux_experiment,
        'pwm_direct_preview':direct_preview,'pwm_direct_numerical_review':direct_numerical_review,
        'pwm_low_cost_comparison':low_cost_comparison,
        'leakage_geometry_review':leakage_geometry,
        'detailed_slot_review':detailed_slot_review,
        'conductor_coordinate_review':conductor_coordinate_review,
        'continuous_packing_review':continuous_packing_review,
        'whole_grid_packing_review':whole_grid_packing_review,
        'dimension_resolution_policy':resolution_policy(),'selected_continuous_packing':selected_continuous_packing,
        'coil_coordinate_proposal':coil_coordinate_proposal,
        'end_routing_review':end_routing_review,'route_adjustment_review':route_adjustment_review,
        'route_conflict_review':route_conflict_review,
        'bundle_routing_review':bundle_routing_review,
        'transition_routing_review':transition_routing_review,
        'clearance_refinement_review':clearance_refinement_review,
        'error':read(folder/'error.json'),'request_contract':plan.get('request_contract'),
        'scope':'Breadloaf 개발용 · 85×20mm / 4극12슬롯 / Delta / Id=0 / 20℃ / 50PN470·N48UH · Flat 보류',
        'production_optimizer_connected':False}


def jobs():
    ids=list(LEGACY)
    if HOME.exists():ids += [p.parent.name for p in HOME.glob('bf_*/metadata.json')]
    return {'jobs':[{k:d[k] for k in ('id','kind','state','title','created')} for d in (detail(i) for i in ids)]}


def action(command,data):
    with LOCK:
        if command=='input-preview':
            from breadloaf_request import adapt
            return adapt(data.get('input_snapshot'),data.get('max_line_peak_A',40),data.get('iterations',10))
        if command=='search':
            contract=None
            if 'input_snapshot' in data:
                from breadloaf_request import adapt
                contract=adapt(data['input_snapshot'],data.get('max_line_peak_A',40),data.get('iterations',10))
                if not contract['can_search']:raise ValueError('; '.join(contract['errors']))
                data={**data,'target_electromagnetic_torque_Nm':contract['target_electromagnetic_torque_Nm'],
                      'max_line_peak_A':contract['max_line_peak_A'],'iterations':contract['iterations']}
            target=data.get('target_electromagnetic_torque_Nm',.5);current=data.get('max_line_peak_A',40);iterations=data.get('iterations',10)
            for value in (target,current):
                if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or value<=0:raise ValueError('Positive finite torque/current required')
            if isinstance(iterations,bool) or not isinstance(iterations,int) or not 1<=iterations<=30:raise ValueError('Iteration budget must be 1..30')
            if any(j['kind']=='search' and j['state'] in ('running','searching') for j in jobs()['jobs']):raise ValueError('Breadloaf search already running')
            job,folder,meta=create('search')
            seed=SEED;extra=[]
            if contract:
                request_path=folder.parent/'request_contract.json';write_json(request_path,contract)
                snapshot=read(SEED);snapshot['expected_native']['ShaftSpeed']=contract['speed_rpm']
                snapshot['expected_native']['DCBusVoltage']=min(contract['voltages_V'])
                seed=folder.parent/'seed_snapshot.json';write_json(seed,snapshot)
                extra=['--request-contract',str(request_path)]
            with (folder.parent/'worker.log').open('wb') as log:
                process=subprocess.Popen([sys.executable,str(ROOT/'validation/optimize_breadloaf_ripple.py'),
                    '--seed-snapshot',str(seed),'--output',str(folder),'--iterations',str(iterations),
                    '--target-electromagnetic-torque',str(target),'--max-line-peak-current',str(current),*extra],
                    cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            meta['pid']=process.pid;write_json(folder.parent/'metadata.json',meta)
            return detail(job)
        job=data.get('id');kind,folder,meta=locate(job)
        if command=='prepare':
            if kind!='search' or detail(job)['state']!='completed':raise ValueError('Completed search required')
            from prepare_breadloaf_verification import prepare
            selected=data.get('selected_ids')
            if not isinstance(selected,list) or not selected:raise ValueError('Select saved candidates')
            # Validate selection before creating a job record.
            available={c['id'] for c in read(folder/'result.json')['finalists']}
            if any(not isinstance(i,str) for i in selected) or len(set(selected))!=len(selected) or not set(selected)<=available:raise ValueError('Invalid distinct saved candidate selection')
            new,batch,_=create('validation',job);prepare(folder,MODEL,batch,selected)
            return detail(new)
        if command=='start':
            if kind not in ('validation','feedback'):raise ValueError('Prepared verification batch required')
            from breadloaf_workflow import start
            start(folder)
            return detail(job)
        if command=='review':
            if kind=='search' or detail(job)['state']!='completed':raise ValueError('Completed native batch required')
            from breadloaf_workflow import review
            review(folder);return detail(job)
        if command=='feedback':
            if kind!='validation' or detail(job)['state']!='completed':raise ValueError('Completed initial validation required; correction budget is one')
            if job=='pilot-validation' and (LEGACY['pilot-feedback'][1]/'result.json').exists():raise ValueError('Current correction already completed; open pilot-feedback')
            # Prevent multiple correction batches for the same parent in the GUI.
            if any(j.get('parent')==job and j['kind']=='feedback' for j in (locate(i['id'])[2] for i in jobs()['jobs'])):raise ValueError('Current correction already prepared')
            from review_breadloaf_verification import review
            check=review(folder)
            if not any(r['practical_ripple_acceptance']['state']=='passed' and r['current_feedback']['status']=='proposed_unverified' for r in check['cases']):
                raise ValueError('No ripple-passed candidate can reach the requested torque within the current limit')
            from prepare_breadloaf_current_feedback import prepare
            new,batch,_=create('feedback',job);prepare(folder,batch)
            return detail(new)
        raise ValueError('Unknown Breadloaf action')
