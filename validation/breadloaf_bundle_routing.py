"""Experimental shared coil corridors. Full pair checks remain mandatory."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from breadloaf_end_routing import curve_statistics,check_curves
from breadloaf_route_adjustment import pair_penalty
from breadloaf_route_conflicts import classify
from study_io import write_json


def corridor_controls(routes,separation,lateral=0.,height_delta=0.):
    if not routes or not np.isfinite([separation,lateral,height_delta]).all() or separation<=0:
        raise ValueError('Routes and positive finite separation required')
    if len({(r['end'],r['coil_index']) for r in routes})!=1:raise ValueError('One coil/end per corridor required')
    P=np.asarray([r['control_points_xyz_mm'] for r in routes],float)
    if P.ndim!=3 or P.shape[1:]!=(6,3) or not np.isfinite(P).all():raise ValueError('Finite quintic routes required')
    starts=P[:,0,:2];ends=P[:,-1,:2];a=starts.mean(axis=0);b=ends.mean(axis=0)
    delta=b-a;length=np.linalg.norm(delta)
    if length<1e-9:raise ValueError('Distinct mean corridor endpoints required')
    normal=np.array([-delta[1],delta[0]])/length
    order=np.argsort(((starts+ends)/2)@normal,kind='stable');ranks=np.empty(len(routes));ranks[order]=np.arange(len(routes))-(len(routes)-1)/2
    height=float(np.median(P[:,2:4,2]))+height_delta
    if height<=0:raise ValueError('Positive corridor control height required')
    result=P.copy()
    for i,rank in enumerate(ranks):
        offset=normal*(lateral+rank*separation)
        result[i,2,:2]=.7*a+.3*b+offset;result[i,3,:2]=.3*a+.7*b+offset
        result[i,2:4,2]=height
    # Internal controls share spaced lanes, but transitions need independent checks.
    return result


def optimise(routes,separation,budget=240,intervals=16):
    if isinstance(budget,bool) or not isinstance(budget,int) or budget<1:raise ValueError('Positive integer budget required')
    start=time.perf_counter();base=copy.deepcopy(routes)
    keys=sorted({(r['end'],r['coil_index']) for r in routes})
    groups=[[i for i,r in enumerate(routes) if (r['end'],r['coil_index'])==key] for key in keys]
    trial=copy.deepcopy(base);params=np.zeros((len(groups),2))
    for indices in groups:
        controls=corridor_controls([base[i] for i in indices],separation)
        for i,P in zip(indices,controls):trial[i]['control_points_xyz_mm']=P.tolist()
    stats=[curve_statistics(r['control_points_xyz_mm'],intervals) for r in trial]
    def costs(changed):
        return sum(pair_penalty(stats[i],stats[j],separation) for i in range(len(routes)) for j in range(i)
                   if routes[i]['end']==routes[j]['end'] and (i in changed or j in changed))
    evaluations=0;changes=0
    # Complete one pass under a fixed budget; joint group moves preserve lane layout.
    for group_index,indices in enumerate(groups):
        old=[stats[i] for i in indices];best=costs(set(indices));choice=None
        for lateral,height in ((-2,0),(2,0),(0,-4),(0,4),(-2,4),(2,4),(0,8),(-4,0),(4,0),(0,-8)):
            if evaluations>=budget:break
            evaluations+=1
            try:controls=corridor_controls([base[i] for i in indices],separation,lateral,height)
            except ValueError:continue
            proposed=[curve_statistics(P,intervals) for P in controls]
            for i,s in zip(indices,proposed):stats[i]=s
            value=costs(set(indices))
            if value<best-1e-10:best=value;choice=(lateral,height,controls,proposed)
        for i,s in zip(indices,old):stats[i]=s
        if choice:
            lateral,height,controls,proposed=choice;params[group_index]=[lateral,height];changes+=1
            for i,P,s in zip(indices,controls,proposed):trial[i]['control_points_xyz_mm']=P.tolist();stats[i]=s
        if evaluations>=budget:break
    for r in trial:
        P=np.asarray(r['control_points_xyz_mm']);world=P.copy();origin=r['control_points_world_xyz_mm'][0][2]
        world[:,2]=origin+(-1 if r['end']=='front' else 1)*P[:,2]
        r['control_points_world_xyz_mm']=world.tolist()
        s=curve_statistics(P,64);r['length_mm']=s['length_mm'];r['sampled_minimum_bend_radius_mm']=s['sampled_minimum_bend_radius_mm']
        r['conservative_control_hull_height_mm']=float(P[:,2].max())
        r.pop('detour_parameters',None)
    return trial,{'group_count':len(groups),'parameter_count':2*len(groups),'evaluations':evaluations,'budget':budget,
                  'changed_corridors_after_initialisation':changes,'coarse_intervals':intervals,
                  'lateral_trial_bounds_mm':[-4,4],'height_delta_trial_bounds_mm':[-8,8],
                  'groups':[{'end':k[0],'coil_index':k[1],'lateral_mm':float(v[0]),'height_delta_mm':float(v[1])} for k,v in zip(keys,params)],
                  'elapsed_s':time.perf_counter()-start,'global_optimum_claimed':False}


def build(direct,persist=True,budget=240):
    start=time.perf_counter();direct=Path(direct).resolve();source=direct/'route_adjustment_review.json'
    original=json.loads(source.read_text(encoding='utf-8'))
    if not original.get('source_files'):raise ValueError('Frozen sources required')
    for p,digest in original['source_files'].items():
        if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest:raise ValueError('Route source changed')
    separation=original['required_centre_separation_mm'];routes=original['routes']
    before,_=check_curves(routes,separation,64)
    if before!=original['selected_check']:raise ValueError('Baseline clearance differs from saved check')
    trial,optimizer=optimise(routes,separation,budget)
    after,_=check_curves(trial,separation,64)
    accepted=(after['confirmed_conflicts']<=before['confirmed_conflicts'] and len(after['nonclear_pairs'])<len(before['nonclear_pairs']))
    selected=trial if accepted else routes
    b=classify(routes,before,separation);a=classify(trial,after,separation)
    immutable=('id','end','coil_index','phase','from_conductor','to_conductor')
    for old,new in zip(routes,trial):
        if any(old[k]!=new[k] for k in immutable) or not np.array_equal(np.asarray(old['control_points_xyz_mm'])[[0,1,4,5]],np.asarray(new['control_points_xyz_mm'])[[0,1,4,5]]):
            raise ValueError('Electrical connection, endpoint or exit tangent changed')
    result={'schema':'breadloaf-bundle-routing-v1','candidate_id':original['candidate_id'],'optimizer':optimizer,
            'baseline_check':before,'trial_check':after,'trial_accepted':accepted,
            'baseline_by_relation':b['by_relation'],'trial_by_relation':a['by_relation'],
            'selected_check':after if accepted else before,'routes':selected,'trial_routes':trial,
            'connection_and_exit_controls_preserved':True,'end_routing_verified':False,'qualified':False,
            'used_for_optimization':False,'new_native_fea':0,'elapsed_s':time.perf_counter()-start,
            'source_files':{str(source):hashlib.sha256(source.read_bytes()).hexdigest(),**original['source_files']},
            'scope':'Shared inner control lanes only. Continuous curves may approach during transitions. Housing, terminals, intercoil connections and bend limits unresolved.'}
    if persist:write_json(direct/'bundle_routing_review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);a=p.parse_args();r=build(a.direct)
    print(json.dumps({k:r[k] for k in ('trial_accepted','baseline_by_relation','trial_by_relation','elapsed_s')},indent=2))
    print(json.dumps({k:r['trial_check'][k] for k in ('confirmed_conflicts','unresolved_pairs')},indent=2))
