"""Bounded coil corridor transition experiment; separate relation guards."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
from collections import Counter
import numpy as np
from breadloaf_end_routing import curve_statistics,segment_distance,check_curves
from study_io import write_json


def elevate_septic(control):
    P=np.asarray(control,float)
    if P.shape!=(6,3) or not np.isfinite(P).all():raise ValueError('Finite quintic controls required')
    while len(P)<8:
        n=len(P)-1
        P=np.array([P[0]]+[(i/(n+1))*P[i-1]+(1-i/(n+1))*P[i] for i in range(1,n+1)]+[P[-1]])
    return P


def transition_controls(routes,start_scale=1.,end_scale=1.,spread_mm=0.):
    if not routes or not np.isfinite([start_scale,end_scale,spread_mm]).all():raise ValueError('Finite transition parameters required')
    if not .5<=start_scale<=1.5 or not .5<=end_scale<=1.5 or abs(spread_mm)>2:
        raise ValueError('Transition outside bounded proposal domain')
    if len({(r['end'],r['coil_index']) for r in routes})!=1:raise ValueError('One coil/end required')
    P=np.array([elevate_septic(r['control_points_xyz_mm']) for r in routes])
    # Rank by endpoint radii, deterministic for ties. These are proposal lanes,
    # not a reconstructed Native winding order.
    radii=np.linalg.norm(P[:,0,:2],axis=1)+np.linalg.norm(P[:,-1,:2],axis=1)
    order=np.argsort(radii,kind='stable');ranks=np.empty(len(P));ranks[order]=np.arange(len(P))-(len(P)-1)/2
    normaliser=max(1,float(np.max(np.abs(ranks))))
    for i,p in enumerate(P):
        p[2,:2]=p[0,:2]+start_scale*(p[2,:2]-p[0,:2])
        p[5,:2]=p[7,:2]+end_scale*(p[5,:2]-p[7,:2])
        p[[2,5],2]+=ranks[i]/normaliser*spread_mm
    if P[:,:,2].min()<0:raise ValueError('Transition enters lamination half-space')
    return P


def relation(a,b):
    return 'same_coil' if a['coil_index']==b['coil_index'] else 'same_phase_other_coil' if a['phase']==b['phase'] else 'different_phase'


def pair_metrics(a,b,separation):
    error=a['linearisation_error_bound_mm']+b['linearisation_error_bound_mm']
    box=np.linalg.norm(np.maximum(0,np.maximum(a['points'].min(axis=0)-b['points'].max(axis=0),b['points'].min(axis=0)-a['points'].max(axis=0))))
    if box-error>=separation:return (0,0,0.)
    distance=segment_distance(a['points'][:-1],a['points'][1:],b['points'][:-1],b['points'][1:])
    lower=max(0,distance-error);upper=distance+error
    return (int(upper<separation),int(lower<separation<=upper),max(0,separation-lower)**2)


def relation_counts(routes,check):
    by_id={r['id']:r for r in routes};counts=Counter()
    for p in check['nonclear_pairs']:
        counts[(relation(by_id[p['route_a']],by_id[p['route_b']]),p['state'])]+=1
    return {r:{'confirmed':counts[(r,'confirmed_curve_conflict')],'unresolved':counts[(r,'unresolved_near_limit')]} for r in ('same_coil','same_phase_other_coil','different_phase')}


def accept_trial(before,after):
    # Every relation/state count must not increase. No hiding a regression in totals.
    values=[(before[r][state],after[r][state]) for r in before for state in ('confirmed','unresolved')]
    return all(a<=b for b,a in values) and any(a<b for b,a in values)


def optimise(routes,separation,budget=240,intervals=32,progress=None):
    if isinstance(budget,bool) or not isinstance(budget,int) or budget<1:raise ValueError('Positive evaluation budget required')
    start=time.perf_counter();base=copy.deepcopy(routes);trial=copy.deepcopy(routes)
    for r in trial:r['control_points_xyz_mm']=elevate_septic(r['control_points_xyz_mm']).tolist()
    stats=[curve_statistics(r['control_points_xyz_mm'],intervals) for r in trial]
    keys=sorted({(r['end'],r['coil_index']) for r in routes});params=[];evaluations=0
    def metrics(indices):
        groups={k:np.zeros(3) for k in ('same_coil','same_phase_other_coil','different_phase')}
        for i in range(len(routes)):
            for j in range(i):
                if routes[i]['end']==routes[j]['end'] and (i in indices or j in indices):
                    groups[relation(routes[i],routes[j])]+=pair_metrics(stats[i],stats[j],separation)
        return groups
    directions=((.5,1,0),(1.5,1,0),(1,.5,0),(1,1.5,0),(.5,.5,0),(1.5,1.5,0),(1,1,1),(1,1,-1),(1,1,2),(1,1,-2))
    for end,coil in keys:
        indices=[i for i,r in enumerate(routes) if (r['end'],r['coil_index'])==(end,coil)]
        old=[stats[i] for i in indices];reference=metrics(set(indices));best=reference;choice=None
        for s,e,h in directions:
            if evaluations>=budget:break
            evaluations+=1
            try:P=transition_controls([base[i] for i in indices],s,e,h)
            except ValueError:continue
            proposed=[curve_statistics(p,intervals) for p in P]
            for i,value in zip(indices,proposed):stats[i]=value
            candidate=metrics(set(indices))
            # Relation-specific confirmed/unresolved guard, then reduce total deficit.
            no_regression=all(np.all(candidate[k][:2]<=reference[k][:2]) for k in reference)
            score=sum(v[2] for v in candidate.values());best_score=sum(v[2] for v in best.values())
            if no_regression and score<best_score-1e-10:best=candidate;choice=(s,e,h,P,proposed)
        for i,value in zip(indices,old):stats[i]=value
        if choice:
            s,e,h,P,proposed=choice
            for i,p,value in zip(indices,P,proposed):trial[i]['control_points_xyz_mm']=p.tolist();stats[i]=value
            params.append({'end':end,'coil_index':coil,'start_scale':s,'end_scale':e,'spread_mm':h})
        if progress:progress({'status':'searching','evaluations':evaluations,'budget':budget,'changed_groups':len(params),'elapsed_s':time.perf_counter()-start})
        if evaluations>=budget:break
    return trial,{'parameter_count':3*len(keys),'group_count':len(keys),'evaluation_budget':budget,'evaluations':evaluations,
                  'coarse_intervals':intervals,'changes':params,'elapsed_s':time.perf_counter()-start,'global_optimum_claimed':False}


def build(direct,persist=True,budget=240):
    start=time.perf_counter();direct=Path(direct).resolve();source=direct/'bundle_routing_review.json'
    original=json.loads(source.read_text(encoding='utf-8'))
    if not original.get('source_files'):raise ValueError('Frozen route sources required')
    for p,digest in original['source_files'].items():
        if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest:raise ValueError('Route source changed')
    routes=original['routes'];separation=1.95
    # Required separation comes from the original route contract, not a new setting.
    route_source=next(Path(p) for p in original['source_files'] if Path(p).name=='route_adjustment_review.json')
    separation=json.loads(route_source.read_text(encoding='utf-8'))['required_centre_separation_mm']
    before,_=check_curves(routes,separation,64)
    if before!=original['selected_check']:raise ValueError('Baseline differs from saved clearance')
    trial,optimizer=optimise(routes,separation,budget,progress=(lambda p:write_json(direct/'transition_routing_progress.json',p)) if persist else None)
    after,statistics=check_curves(trial,separation,64)
    b=relation_counts(routes,before);a=relation_counts(trial,after);accepted=accept_trial(b,a)
    for old,new,stat in zip(routes,trial,statistics):
        oldP=elevate_septic(old['control_points_xyz_mm']);P=np.asarray(new['control_points_xyz_mm'])
        if any(old[k]!=new[k] for k in ('id','end','coil_index','phase','from_conductor','to_conductor')) or not np.array_equal(oldP[[0,1,6,7]],P[[0,1,6,7]]):
            raise ValueError('Connection or exit controls changed')
        world=P.copy();world[:,2]=old['control_points_world_xyz_mm'][0][2]+(-1 if new['end']=='front' else 1)*P[:,2]
        new['control_points_world_xyz_mm']=world.tolist();new['length_mm']=stat['length_mm']
        new['sampled_minimum_bend_radius_mm']=stat['sampled_minimum_bend_radius_mm']
        new['conservative_control_hull_height_mm']=float(P[:,2].max())
    result={'schema':'breadloaf-transition-routing-v1','candidate_id':original['candidate_id'],'optimizer':optimizer,
            'baseline_check':before,'trial_check':after,'baseline_by_relation':b,'trial_by_relation':a,
            'trial_accepted':accepted,'selected_check':after if accepted else before,'routes':trial if accepted else routes,'trial_routes':trial,
            'acceptance_rule':'No increase in confirmed OR unresolved counts for ANY coil/phase relation; at least one count decreases. Equal 64-interval checks.',
            'connection_and_exit_controls_preserved':True,'end_routing_verified':False,'qualified':False,'used_for_optimization':False,
            'phase_resistance_applied_ohm':None,'end_inductance_H':None,'new_native_fea':0,'elapsed_s':time.perf_counter()-start,
            'source_files':{str(source):hashlib.sha256(source.read_bytes()).hexdigest(),**original['source_files']},
            'scope':'Degree-seven transition controls only. No housing, terminals, intercoil route or bend-limit qualification.'}
    if persist:
        write_json(direct/'transition_routing_review.json',result)
        write_json(direct/'transition_routing_progress.json',{'status':'completed','trial_accepted':accepted,'elapsed_s':result['elapsed_s']})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);a=p.parse_args();r=build(a.direct)
    print(json.dumps({k:r[k] for k in ('trial_accepted','baseline_by_relation','trial_by_relation','elapsed_s')},indent=2))
