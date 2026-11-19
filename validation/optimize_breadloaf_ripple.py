"""Experimental, offline three-variable Breadloaf ripple minimization.

Fixed geometry envelope/material/winding/Id=0. No FEA, efficiency or voltage
qualification. Integer ticks enforce 0.1 mm lengths without exhaustive sweep.
"""
import argparse
import copy
import hashlib
import json
import time
from types import SimpleNamespace
from pathlib import Path

from scipy.optimize import differential_evolution

from breadloaf_boundary import boundary
from spm_ripple import predict
from spm_ripple_operating_point import match_torque
from study_io import write_json
from breadloaf_search_space import search_space
from breadloaf_screens import evaluate as evaluate_screens,reference as screen_reference
from breadloaf_shaft_control import solve as solve_shaft

ROOT=Path(__file__).resolve().parent


def make_snapshot(seed, ticks):
    s=copy.deepcopy(seed)
    if s['rotor_id']!='surface_breadloaf':raise ValueError('Breadloaf only')
    opening,arc,reduction=[int(round(x))/10 for x in ticks]
    n=s['expected_native'];g=s['geometry_mm']
    n.update(Slot_Opening=opening,MagnetReduction=reduction)
    n['Magnet_Arc_[ED]']=arc;g['Slot_Opening']=opening
    region,derived=boundary(g['Stator_Bore'],g['Airgap'],g['Magnet_Thickness'],arc,reduction,s['poles'])
    pitch=3.141592653589793*g['Stator_Bore']/s['slots']
    if opening+g['Tooth_Width']>=pitch:raise ValueError('Opening and tooth exceed pitch')
    s['magnet_region']=region;s.pop('native_readback',None)
    s['id']='breadloaf_search_'+ '_'.join(str(int(round(x))) for x in ticks)
    s['geometry_provenance']='Inferred analytic boundary matched to saved Native templates; new dimensions not SDK-readback verified.'
    s['boundary_derived']=derived
    return s


def run(seed_path,output,target=.5,max_current=40,iterations=10,request_contract=None,
        random_seeds=(20261104,),initial_ticks=None):
    if not random_seeds or any(isinstance(s,bool) or not isinstance(s,int) or s<0 for s in random_seeds):
        raise ValueError('Nonnegative integer search seeds required')
    if request_contract is not None:
        if not request_contract.get('can_search'):raise ValueError('Validated supported input contract required')
        target=request_contract['target_electromagnetic_torque_Nm'];max_current=request_contract['max_line_peak_A']
    started=time.perf_counter();seed_path=Path(seed_path).resolve();output=Path(output).resolve()
    policy=json.loads((ROOT/'spm_ripple_development_policy.json').read_text(encoding='utf-8'))
    if policy['rotors']['surface_breadloaf']['development_status'] not in ('active','active_priority'):
        raise ValueError('Breadloaf development not active')
    if output.exists():raise ValueError('Fresh output folder required')
    output.mkdir(parents=True);seed=json.loads(seed_path.read_text(encoding='utf-8'))
    if target<=0 or max_current<=0 or iterations<1:raise ValueError('Positive target, current and iteration budget required')
    space=search_space(request_contract.get('ui_input_snapshot') if request_contract else None)
    ref=screen_reference() if request_contract else None
    local_model=None
    model_path=ROOT.parent/'outputs/breadloaf_loss_B_validation_20261104/local_loss_B_model.json'
    if request_contract and model_path.is_file():local_model=json.loads(model_path.read_text(encoding='utf-8'))
    bounds=space['tick_bounds'];free=[i for i,(lo,hi) in enumerate(bounds) if lo!=hi]
    initial_ticks=initial_ticks or []
    for ticks in initial_ticks:
        if len(ticks)!=3 or any(not isinstance(v,(int,float)) or not float(v).is_integer() or not lo<=v<=hi
                                for v,(lo,hi) in zip(ticks,bounds)):
            raise ValueError('Initial dimensions must be integer ticks inside the current search space')
    population=max(5,5*len(free)) if free else 1
    plan={'schema':'breadloaf-ripple-search-v1','seed_snapshot':str(seed_path),
          'seed_sha256':hashlib.sha256(seed_path.read_bytes()).hexdigest(),
          'variables':space['variables'],'free_variable_count':space['free_variable_count'],
          'fixed_variable_count':space['fixed_variable_count'],
          'grid_combinations_before_geometry_screen':space['full_grid_combinations'],
          'algorithm':'SciPy differential_evolution, integer ticks, deduplicated evaluations',
          'seed':random_seeds[0],'search_seeds':list(random_seeds),'population':population,'maxiter':iterations,
          'max_optimizer_objective_calls':population*(iterations+1)*len(random_seeds) if free else 1,
          'initial_recomputed_candidates':len(initial_ticks),
          'stopping_policy':'tol=0, atol=0: use bounded search budget unless population energies become identical; no relative tolerance on compressed ripple score.',
          'target_electromagnetic_torque_Nm':target,'max_line_peak_A':max_current,
          'objective':'Raw predicted peak-to-peak torque / absolute mean torque; reject invalid geometry or unmet target current.',
          'scope':'Experimental ripple-only search, fixed stator D85/L20 and winding; not a full motor requirement optimization.',
          'bounds_policy':'Exploratory search bounds, not manufacturer-approved manufacturing limits.',
          'spatial_points':1440,'rotor_points':240,'native_fea_calls':0,
          'production_optimizer_connected':False}
    if request_contract is not None:plan['request_contract']=request_contract
    if request_contract:plan['current_control_method']='Shaft target with local loss model inside development hull; explicitly unverified lower-bound fallback outside.'
    if ref:
        plan['model_screen_reference']=ref
        local_path=ROOT.parent/'outputs/breadloaf_loss_B_validation_20261104/local_loss_B_model.json'
        if local_path.is_file():plan['local_loss_B_model_sha256']=hashlib.sha256(local_path.read_bytes()).hexdigest()
        plan['modeled_constraint_policy']='Provisional voltage/copper-efficiency-bound guidance; section-B diagnostic only. Retain best-ripple reference too. No FEA qualification.'
    write_json(output/'plan.json',plan)
    cache={};calls=0
    def match_point(raw,s):
        if request_contract and local_model:
            return solve_shaft(raw,s,request_contract['requested_shaft_torque_Nm'],max_current,ref,request_contract,local_model)
        if request_contract:
            fallback=match_torque(raw,s['line_peak_A'],target,max_current)
            return {**fallback,'status':'shaft_matching_unverified','shaft_control_status':'unverified',
                    'shaft_control_reason':'No local shaft/loss model available','control_torque_basis':'electromagnetic_lower_bound_only'}
        return match_torque(raw,s['line_peak_A'],target,max_current)
    def objective(x):
        nonlocal calls
        calls+=1;key=tuple(int(round(v)) for v in x)
        if key in cache:return cache[key]['objective']
        record={'ticks':list(key)}
        try:
            s=make_snapshot(seed,key);raw=predict(s,1440,240)
            matched=match_point(raw,s)
            record.update(id=s['id'],dimensions={k:s['expected_native'][k] for k in ('Slot_Opening','Magnet_Arc_[ED]','MagnetReduction')},
                          status=matched['status'],matched={k:v for k,v in matched.items() if k!='torque_Nm'})
            is_matched=matched['status'] in ('matched_in_linear_model','matched_shaft_in_local_model')
            score=matched['ripple_pct'] if is_matched else 15000.+matched.get('torque_shortfall_Nm',0)/target if matched['status']=='shaft_matching_unverified' else 10000.+1000*matched['torque_shortfall_Nm']/target
            if ref:
                screens=matched.get('model_screens') or evaluate_screens(raw,s,matched['line_peak_A'],ref,request_contract)
                record['model_screens']=screens
                if is_matched:
                    deficit=screens['normalized_violation'];ripple_score=matched['ripple_pct']/(1+matched['ripple_pct'])
                    score=1+deficit/(1+deficit)+1e-6*ripple_score if deficit else ripple_score
        except ValueError as exc:
            record.update(status='geometry_rejected',reason=str(exc));score=20000.
        record['objective']=float(score);cache[key]=record
        return float(score)
    def callback(x,convergence):
        write_json(output/'progress.json',{'status':'searching','unique_evaluations':len(cache),
                   'objective_calls':calls,'elapsed_s':time.perf_counter()-started,'best_objective':objective(x)})
    def expand(x):
        values=[lo for lo,hi in bounds]
        for index,value in zip(free,x):values[index]=value
        return values
    for ticks in initial_ticks:objective(ticks)
    runs=[]
    if free:
        for random_seed in random_seeds:
            best=min(cache.values(),key=lambda r:r['objective'])['ticks'] if cache else None
            result=differential_evolution(lambda x:objective(expand(x)),[bounds[i] for i in free],integrality=[True]*len(free),seed=random_seed,
                maxiter=iterations,popsize=5,polish=False,workers=1,updating='immediate',tol=0,atol=0,
                x0=[best[i] for i in free] if best is not None else None,
                callback=lambda x,convergence:callback(expand(x),convergence))
            runs.append({'seed':random_seed,'success':bool(result.success),'message':str(result.message),'nfev':int(result.nfev),
                         'best_objective':float(result.fun)})
    else:
        objective(expand([]))
        result=SimpleNamespace(success=True,message='All three dimensions fixed; evaluated one candidate.',nfev=1)
    valid=sorted([r for r in cache.values() if r['status'] in ('matched_in_linear_model','matched_shaft_in_local_model')],key=lambda r:r['objective'])
    best_effort=sorted([r for r in cache.values() if r['status'] in ('target_not_reached_within_current_limit','shaft_target_not_reached_within_domain')],key=lambda r:r['objective'])
    unknown=sorted([r for r in cache.values() if r['status']=='shaft_matching_unverified'],key=lambda r:r['objective'])
    finalists=[]
    selected=(valid if valid else best_effort if best_effort else unknown)[:3]
    if ref and valid:
        ripple_reference=min(valid,key=lambda r:r['matched']['ripple_pct'])
        if ripple_reference['id'] not in {r['id'] for r in selected}:selected=selected[:2]+[ripple_reference]
    for row in selected:
        s=make_snapshot(seed,row['ticks']);levels=[]
        for spatial,rotor in ((1440,240),(2880,480),(5760,960)):
            raw=predict(s,spatial,rotor);matched=match_point(raw,s)
            levels.append({'spatial_points':spatial,'rotor_points':rotor,
                           **{k:v for k,v in matched.items() if k!='torque_Nm'}})
            if ref:levels[-1]['model_screens']=evaluate_screens(raw,s,matched['line_peak_A'],ref,request_contract)
        write_json(output/(s['id']+'_snapshot.json'),s)
        write_json(output/(s['id']+'_high_resolution.json'),{'raw_proxy':raw,'matched':matched})
        delta=None
        if all('ripple_pct' in v for v in levels[-2:]):delta=abs(levels[-1]['ripple_pct']-levels[-2]['ripple_pct'])
        finalists.append({'id':s['id'],'dimensions':row['dimensions'],'levels':levels,
                         'selection_reason':'best_ripple_reference' if ref and valid and row['id']==ripple_reference['id'] else 'modeled_constraint_guidance' if ref else 'raw_ripple',
                         'last_refinement_change_percentage_points':delta,'qualified':False,
                         'native_geometry_readback_required':True,'native_fea_required':True})
    report={'schema':'breadloaf-ripple-search-result-v1','plan':plan,
            'elapsed_s':time.perf_counter()-started,'objective_calls_including_progress_reads':calls,
            'unique_candidates':len(cache),'valid_current_matched_candidates':len(valid),
            'rejected_geometry_candidates':sum(r['status']=='geometry_rejected' for r in cache.values()),
            'current_limit_rejected_candidates':len(best_effort),'shaft_control_unverified_candidates':len(unknown),
            'optimizer_success':bool(result.success),'optimizer_message':str(result.message),
            'optimizer_nfev':sum(r['nfev'] for r in runs) if runs else int(result.nfev),
            'optimizer_runs':runs,'finalists':finalists,'qualified':False,
            'selection_status':'shaft_model_matched_candidates' if valid and request_contract else 'current_matched_candidates' if valid else 'best_effort_current_limited' if best_effort else 'shaft_control_unverified' if unknown else 'no_valid_geometry',
            'production_optimizer_connected':False,'native_fea_calls':0,
            'limitations':['Raw linear prototype only. Ripple ranking can be wrong; no independent current-matched validation.',
                           'Numerical refinement difference is reported, not declared converged by an arbitrary threshold.',
                           'No voltage, saturation, efficiency, demagnetization or manufacturing qualification.',
                           'Flat deferred. No thermal, structural or skew analysis.']}
    write_json(output/'evaluations.json',list(cache.values()));write_json(output/'result.json',report)
    write_json(output/'progress.json',{'status':'completed','unique_candidates':len(cache),'elapsed_s':report['elapsed_s']})
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seed-snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--iterations',type=int,default=10)
    p.add_argument('--target-electromagnetic-torque',type=float,default=.5)
    p.add_argument('--max-line-peak-current',type=float,default=40)
    p.add_argument('--request-contract',type=Path)
    p.add_argument('--search-seeds',type=int,nargs='+',default=[20261104])
    p.add_argument('--warm-start-study',type=Path,help='Only initial dimensions are reused; all metrics are recomputed.')
    a=p.parse_args();initial=None
    if a.warm_start_study:
        previous=json.loads((a.warm_start_study/'result.json').read_text(encoding='utf-8'))
        initial=[[round(f['dimensions'][key]*10) for key in ('Slot_Opening','Magnet_Arc_[ED]','MagnetReduction')] for f in previous['finalists']]
    r=run(a.seed_snapshot,a.output,a.target_electromagnetic_torque,a.max_line_peak_current,a.iterations,
        json.loads(a.request_contract.read_text(encoding='utf-8')) if a.request_contract else None,a.search_seeds,initial)
    print(json.dumps({k:r[k] for k in ('elapsed_s','unique_candidates','valid_current_matched_candidates','optimizer_message')},indent=2))
