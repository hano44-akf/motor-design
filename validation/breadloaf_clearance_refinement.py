"""Refine only undecided curve-pair distances with explicit error/work limits."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from breadloaf_end_routing import curve_statistics,segment_distance,check_curves
from breadloaf_transition_routing import relation_counts,accept_trial
from study_io import write_json


def refine(routes,initial,separation,max_intervals=1024,pair_budget=400,error_target_mm=.00005,progress=None):
    if not np.isfinite([separation,error_target_mm]).all() or separation<=0 or error_target_mm<=0:
        raise ValueError('Positive finite separation and error target required')
    start_n=initial['intervals_per_curve']
    if any(isinstance(v,bool) or not isinstance(v,int) or v<1 for v in (max_intervals,pair_budget,start_n)) or max_intervals<start_n:
        raise ValueError('Valid refinement and work limits required')
    by_id={r['id']:r for r in routes}
    if len(by_id)!=len(routes):raise ValueError('Unique route identifiers required')
    cache={};pairs=copy.deepcopy(initial['nonclear_pairs']);evaluations=0;history=[]
    def stats(route_id,n):
        key=(route_id,n)
        if key not in cache:cache[key]=curve_statistics(by_id[route_id]['control_points_xyz_mm'],n)
        return cache[key]
    for pair in pairs:
        pair['intervals_per_curve']=start_n;pair['refinement_stop']='already_confirmed' if pair['state']=='confirmed_curve_conflict' else None
        a,b=pair['route_a'],pair['route_b']
        if a not in by_id or b not in by_id or by_id[a]['end']!=by_id[b]['end']:raise ValueError('Invalid same-end route pair')
    n=start_n
    while n<max_intervals:
        n=min(2*n,max_intervals);changed=0
        for pair in pairs:
            if pair['state']!='unresolved_near_limit' or pair['refinement_stop']:continue
            if evaluations>=pair_budget:
                pair['refinement_stop']='pair_budget_exhausted';continue
            a=stats(pair['route_a'],n);b=stats(pair['route_b'],n)
            error=a['linearisation_error_bound_mm']+b['linearisation_error_bound_mm']
            # Chunk one segment set to keep temporary arrays bounded at high n.
            distance=min(segment_distance(a['points'][i:min(i+64,n)],a['points'][i+1:min(i+64,n)+1],
                                         b['points'][:-1],b['points'][1:]) for i in range(0,n,64))
            evaluations+=1;lower=max(pair['distance_lower_bound_mm'],max(0,distance-error))
            upper=min(pair['distance_upper_bound_mm'],distance+error)
            if lower>upper+1e-10:raise ValueError('Inconsistent nested distance bounds')
            state='confirmed_curve_conflict' if upper<separation else 'clear_with_error_bound' if lower>=separation else 'unresolved_near_limit'
            pair.update(polyline_distance_mm=distance,distance_lower_bound_mm=lower,distance_upper_bound_mm=upper,
                        state=state,intervals_per_curve=n)
            if state!='unresolved_near_limit':pair['refinement_stop']='resolved';changed+=1
            elif error<=error_target_mm:pair['refinement_stop']='error_target_reached_unresolved'
            if progress:progress({'intervals':n,'pair_evaluations':evaluations,'pair_budget':pair_budget})
        history.append({'intervals':n,'resolved_in_pass':changed,'pair_evaluations':evaluations,
                        'remaining_unresolved':sum(p['state']=='unresolved_near_limit' for p in pairs)})
        if all(p['state']!='unresolved_near_limit' or p['refinement_stop'] for p in pairs):break
    for pair in pairs:
        if pair['state']=='unresolved_near_limit' and not pair['refinement_stop']:pair['refinement_stop']='interval_limit_reached'
    nonclear=[p for p in pairs if p['state']!='clear_with_error_bound']
    return {'initial_intervals_per_curve':start_n,'max_intervals':max_intervals,'error_target_mm':error_target_mm,
            'pair_budget':pair_budget,'pair_evaluations':evaluations,'history':history,
            'initial_unresolved_pairs':initial['unresolved_pairs'],
            'resolved_to_conflict':sum(p['state']=='confirmed_curve_conflict' and p['refinement_stop']=='resolved' for p in pairs),
            'resolved_to_clear':sum(p['state']=='clear_with_error_bound' for p in pairs),
            'confirmed_conflicts':sum(p['state']=='confirmed_curve_conflict' for p in nonclear),
            'unresolved_pairs':sum(p['state']=='unresolved_near_limit' for p in nonclear),
            'nonclear_pairs':nonclear,'refined_pairs':pairs,'all_modelled_routes_clear':not nonclear}


def build(direct,persist=True):
    start=time.perf_counter();direct=Path(direct).resolve();source=direct/'transition_routing_review.json'
    original=json.loads(source.read_text(encoding='utf-8'))
    if not original.get('source_files'):raise ValueError('Frozen source files required')
    for p,digest in original['source_files'].items():
        if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest:raise ValueError('Route source changed')
    upstream=next(Path(p) for p in original['source_files'] if Path(p).name=='route_adjustment_review.json')
    separation=json.loads(upstream.read_text(encoding='utf-8'))['required_centre_separation_mm']
    # Selected routes in the historical report are the retained baseline.
    if original['trial_accepted']:raise ValueError('This paired review requires the historical retained baseline')
    cases={}
    for name,routes,stored in (('baseline',original['routes'],original['baseline_check']),('trial',original['trial_routes'],original['trial_check'])):
        fresh,_=check_curves(routes,separation,64)
        if fresh!=stored:raise ValueError('Stored clearance differs from recomputation')
        refined=refine(routes,fresh,separation,progress=(lambda p:write_json(direct/'clearance_refinement_progress.json',{'status':'refining','case':name,**p})) if persist else None)
        refined['by_relation']=relation_counts(routes,refined);cases[name]=refined
    accepted=accept_trial(cases['baseline']['by_relation'],cases['trial']['by_relation'])
    result={'schema':'breadloaf-clearance-refinement-v1','candidate_id':original['candidate_id'],'required_centre_separation_mm':separation,
            'cases':cases,'trial_meets_refined_comparison_rule':accepted,'geometry_changed':False,'selection_applied':False,
            'comparison_rule':original['acceptance_rule'],'end_routing_verified':False,'qualified':False,'used_for_optimization':False,
            'phase_resistance_applied_ohm':None,'end_inductance_H':None,'new_native_fea':0,'elapsed_s':time.perf_counter()-start,
            'source_files':{str(source):hashlib.sha256(source.read_bytes()).hexdigest(),**original['source_files']},
            'scope':'Numerical refinement of undecided pairs only. Original clear/conflict certificates retained. Error target is a stopping rule, never clearance tolerance. No physical routing qualification.'}
    if persist:
        write_json(direct/'clearance_refinement_review.json',result)
        write_json(direct/'clearance_refinement_progress.json',{'status':'completed','elapsed_s':result['elapsed_s']})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);a=p.parse_args();r=build(a.direct)
    print(json.dumps({'cases':{k:{x:v[x] for x in ('initial_unresolved_pairs','resolved_to_conflict','resolved_to_clear','confirmed_conflicts','unresolved_pairs','pair_evaluations','by_relation')} for k,v in r['cases'].items()},
                      'trial_meets_refined_comparison_rule':r['trial_meets_refined_comparison_rule'],'elapsed_s':r['elapsed_s']},indent=2))
