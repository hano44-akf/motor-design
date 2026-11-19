"""Budgeted lateral/height detours, with equal-resolution before/after gates.

Cubic degree elevation preserves the initial curve. Only inner quintic controls
move, so conductor endpoints and axial exit tangents remain fixed. Bounded
heuristic search is not a routing/manufacturing or global-optimum certificate.
"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from breadloaf_end_routing import bezier,curve_statistics,segment_distance,check_curves
from study_io import write_json


def elevate(control):
    P=np.asarray(control,float)
    if P.shape!=(4,3) or not np.all(np.isfinite(P)):raise ValueError('Finite cubic controls required')
    while len(P)<6:
        n=len(P)-1
        P=np.array([P[0]]+[(i/(n+1))*P[i-1]+(1-i/(n+1))*P[i] for i in range(1,n+1)]+[P[-1]])
    return P


def detour(base,lateral_mm,height_delta_mm):
    base=np.asarray(base,float)
    if base.shape!=(6,3) or not np.all(np.isfinite(base)) or not all(math.isfinite(v) for v in (lateral_mm,height_delta_mm)):
        raise ValueError('Finite quintic controls and offsets required')
    if abs(lateral_mm)>3 or abs(height_delta_mm)>4:raise ValueError('Detour outside bounded proposal domain')
    delta=base[-1,:2]-base[0,:2];length=np.linalg.norm(delta)
    if length<=0:raise ValueError('Distinct route endpoints required')
    normal=np.array([-delta[1],delta[0]])/length;P=base.copy()
    P[2:4,:2]+=normal*lateral_mm;P[2:4,2]+=height_delta_mm
    if P[:,2].min()<0:raise ValueError('Route would enter lamination half-space')
    return P


def pair_penalty(a,b,separation):
    error=a['linearisation_error_bound_mm']+b['linearisation_error_bound_mm']
    box=np.linalg.norm(np.maximum(0,np.maximum(a['points'].min(axis=0)-b['points'].max(axis=0),b['points'].min(axis=0)-a['points'].max(axis=0))))
    if box-error>=separation:return 0.
    distance=segment_distance(a['points'][:-1],a['points'][1:],b['points'][:-1],b['points'][1:])
    return max(0,separation-max(0,distance-error))**2


def search(routes,separation,evaluation_budget=520,coarse_intervals=16,passes=2,progress=None):
    if any(isinstance(v,bool) or not isinstance(v,int) or v<1 for v in (evaluation_budget,passes)) or not math.isfinite(separation) or separation<=0:
        raise ValueError('Positive budgets and separation required')
    if isinstance(coarse_intervals,bool) or not isinstance(coarse_intervals,int) or coarse_intervals<4:raise ValueError('At least four coarse intervals required')
    started=time.perf_counter();routes=copy.deepcopy(routes);base=[elevate(r['control_points_xyz_mm']) for r in routes]
    parameters=np.zeros((len(routes),2));stats=[curve_statistics(P,coarse_intervals) for P in base]
    penalties=np.zeros((len(routes),len(routes)))
    for i in range(len(routes)):
        for j in range(i):
            if routes[i]['end']==routes[j]['end']:penalties[i,j]=penalties[j,i]=pair_penalty(stats[i],stats[j],separation)
    initial=float(penalties.sum()/2);evaluations=0;changes=[];rejected=0
    directions=[(-1,0),(1,0),(-2,0),(2,0),(0,-2),(0,2),(-2,2),(2,2),(-3,0),(3,0),(0,4),(-2,-2),(2,-2)]
    for pass_index in range(passes):
        order=np.argsort(-penalties.sum(axis=1),kind='stable');changed=False
        for index in order:
            if evaluations>=evaluation_budget:break
            old_value=float(penalties[index].sum());best_value=old_value;chosen=None
            for da,dh in directions:
                if evaluations>=evaluation_budget:break
                value=parameters[index]+[da,dh];evaluations+=1
                try:P=detour(base[index],*value)
                except ValueError:rejected+=1;continue
                candidate=curve_statistics(P,coarse_intervals);costs=np.zeros(len(routes))
                for j,other in enumerate(stats):
                    if j!=index and routes[index]['end']==routes[j]['end']:costs[j]=pair_penalty(candidate,other,separation)
                score=float(costs.sum())
                if score<best_value-1e-10:best_value=score;chosen=(value,P,candidate,costs)
            if chosen:
                value,P,candidate,costs=chosen;parameters[index]=value;stats[index]=candidate
                penalties[index,:]=costs;penalties[:,index]=costs;changed=True
                routes[index]['control_points_xyz_mm']=P.tolist()
                changes.append({'route_id':routes[index]['id'],'pass':pass_index,'lateral_mm':float(value[0]),'inner_height_delta_mm':float(value[1]),
                                'incident_penalty_before':old_value,'incident_penalty_after':best_value})
            if progress:progress({'status':'searching','evaluations':evaluations,'budget':evaluation_budget,'changed_routes':len(changes),'elapsed_s':time.perf_counter()-started})
        if not changed or evaluations>=evaluation_budget:break
    # Elevation alone is geometry-preserving, including untouched routes.
    for i,route in enumerate(routes):
        if parameters[i].tolist()==[0.,0.]:route['control_points_xyz_mm']=base[i].tolist()
        route['detour_parameters']={'lateral_mm':float(parameters[i,0]),'inner_height_delta_mm':float(parameters[i,1])}
        old_world=np.asarray(route['control_points_world_xyz_mm']);P=np.asarray(route['control_points_xyz_mm']);world=P.copy()
        sign=-1 if route['end']=='front' else 1;world[:,2]=old_world[0,2]+sign*P[:,2]
        route['control_points_world_xyz_mm']=world.tolist()
    return routes,{'algorithm':'Budgeted block coordinate lateral/height search, conservative coarse clearance penalty',
        'parameter_count':2*len(routes),'evaluation_budget':evaluation_budget,'evaluations':evaluations,'rejected_parameter_trials':rejected,
        'coarse_intervals':coarse_intervals,'initial_penalty':initial,'final_penalty':float(penalties.sum()/2),
        'changes':changes,'changed_routes':int(np.any(parameters!=0,axis=1).sum()),'elapsed_s':time.perf_counter()-started,
        'lateral_bound_mm':[-3,3],'inner_height_delta_bound_mm':[-4,4],'global_optimum_claimed':False}


def build(direct,persist=True,evaluation_budget=520,final_intervals=64):
    started=time.perf_counter();direct=Path(direct).resolve();source=direct/'end_routing_review.json'
    original=json.loads(source.read_text(encoding='utf-8'))
    if not original.get('source_files'):raise ValueError('Frozen route sources required')
    for p,digest in original['source_files'].items():
        if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest:raise ValueError('Initial route source changed')
    from breadloaf_end_routing import build as recheck
    fresh=recheck(direct,persist=False,intervals=4)
    if any(a['control_points_xyz_mm']!=b['control_points_xyz_mm'] or a['id']!=b['id'] for a,b in zip(original['routes'],fresh['routes'])) or len(original['routes'])!=len(fresh['routes']):
        raise ValueError('Initial routes differ from source assignment')
    separation=original['required_centre_separation_mm']
    before,_=check_curves(original['routes'],separation,final_intervals)
    trial,optimizer=search(original['routes'],separation,evaluation_budget,
        progress=(lambda r:write_json(direct/'route_adjustment_progress.json',r)) if persist else None)
    after,trial_stats=check_curves(trial,separation,final_intervals)
    old_nonclear=before['confirmed_conflicts']+before['unresolved_pairs'];new_nonclear=after['confirmed_conflicts']+after['unresolved_pairs']
    accepted=new_nonclear<old_nonclear and after['confirmed_conflicts']<=before['confirmed_conflicts']
    selected=trial if accepted else copy.deepcopy(original['routes']);selected_check=after if accepted else before
    selected_stats=trial_stats if accepted else [curve_statistics(r['control_points_xyz_mm'],final_intervals) for r in selected]
    for route,stat in zip(selected,selected_stats):
        route['length_mm']=stat['length_mm']
        route['sampled_minimum_bend_radius_mm']=stat['sampled_minimum_bend_radius_mm']
        route['baseline_proposed_peak_height_mm']=route.pop('proposed_peak_height_mm',None)
        route['conservative_control_hull_height_mm']=float(np.asarray(route['control_points_xyz_mm'])[:,2].max())
    ends=[]
    for end in ('front','rear'):
        controls=[np.asarray(r['control_points_xyz_mm']) for r in selected if r['end']==end]
        ends.append({'end':end,'conservative_control_hull_axial_extent_mm':max(P[:,2].max() for P in controls)+original['wire_outer_diameter_mm']/2,
                     'available_axial_space_mm':None,'housing_clearance_verified':False})
    result={'schema':'breadloaf-end-route-adjustment-v1','candidate_id':original['candidate_id'],'optimizer':optimizer,
        'baseline_check':before,'trial_check':after,'selected_check':selected_check,'trial_accepted':accepted,
        'acceptance_rule':'Same-resolution nonclear pairs strictly reduced, and confirmed spacing violations not increased; no physical routing qualification',
        'routes':selected,'ends':ends,'route_count':len(selected),'required_centre_separation_mm':separation,
        'end_routing_verified':False,'qualified':False,'used_for_optimization':False,'new_native_fea':0,
        'phase_resistance_applied_ohm':None,'end_inductance_H':None,'elapsed_s':time.perf_counter()-started,
        'source_files':{str(source):hashlib.sha256(source.read_bytes()).hexdigest(),**original['source_files']},
        'scope':'Bounded experimental quintic detours; fixed conductor endpoints and axial exit tangents. Coil links, terminals, housing exclusions and manufacturing remain unverified.'}
    if persist:
        write_json(direct/'route_adjustment_review.json',result)
        write_json(direct/'route_adjustment_progress.json',{'status':'completed','trial_accepted':accepted,'elapsed_s':result['elapsed_s']})
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);p.add_argument('--evaluations',type=int,default=520);a=p.parse_args();r=build(a.direct,evaluation_budget=a.evaluations)
    print(json.dumps({'accepted':r['trial_accepted'],'before':{k:v for k,v in r['baseline_check'].items() if k!='nonclear_pairs'},
        'after':{k:v for k,v in r['selected_check'].items() if k!='nonclear_pairs'},'optimizer':{k:v for k,v in r['optimizer'].items() if k!='changes'},'elapsed_s':r['elapsed_s']},indent=2))
