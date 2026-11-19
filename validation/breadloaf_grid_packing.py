"""Whole-cavity 0.1mm candidate graph with valid clique cuts and bounded MILP.

Only the conductor-centre grid is enumerated, not motor design combinations.
No inference from timeout/error to impossibility. A saved Native line/arc check
must validate any proposed packing independently of the optimisation model.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from scipy.optimize import milp,Bounds,LinearConstraint
from scipy.sparse import coo_matrix
from scipy.spatial.distance import pdist
from breadloaf_slot_detail import fields,dimensions
from breadloaf_conductor_audit import boundary_margin
from breadloaf_continuous_packing import verify_native_boundary
from study_io import write_json


def candidate_grid(d,diameter,wall):
    if not all(math.isfinite(v) for v in (diameter,wall)) or diameter<=0 or wall<0:raise ValueError('Positive diameter/nonnegative wall required')
    # Wide conservative box includes the whole circular cavity.
    radius=d['back_R']-d['Liner_Thickness']
    xs=np.arange(math.ceil(d['body_front_x']*10),math.floor(radius*10)+1)
    ys=np.arange(-math.ceil(radius*10),math.ceil(radius*10)+1)
    x,y=np.meshgrid(xs,ys);ticks=np.c_[x.ravel(),y.ravel()]
    return ticks[boundary_margin(d,ticks/10,diameter)>=wall-1e-10]


def solve_grid(ticks,target,minimum_distance_mm,reference=None,time_budget_s=30,per_solve_s=3,max_rounds=30,progress=None):
    ticks=np.asarray(ticks)
    if ticks.ndim!=2 or ticks.shape[1]!=2 or not np.all(np.isfinite(ticks)) or not np.all(ticks==np.round(ticks)):
        raise ValueError('Integer 0.1mm grid coordinates required')
    if len(np.unique(ticks,axis=0))!=len(ticks):raise ValueError('Duplicate grid coordinates')
    if isinstance(target,bool) or not isinstance(target,int) or target<2:raise ValueError('Integer target at least two required')
    if not all(math.isfinite(v) and v>0 for v in (minimum_distance_mm,time_budget_s,per_solve_s)):raise ValueError('Positive finite separation/time budgets required')
    if isinstance(max_rounds,bool) or not isinstance(max_rounds,int) or max_rounds<1:raise ValueError('Positive round budget required')
    started=time.perf_counter();n=len(ticks);limit=(minimum_distance_mm*10)**2
    # Integer squared distances strictly below this physical threshold conflict.
    conflict_max=math.ceil(limit-1e-10)-1;cliques=[];known=set();history=[];found=None;relaxation_infeasible=False
    def add(indices):
        indices=tuple(sorted(set(map(int,indices))))
        if len(indices)<2 or indices in known:return False
        # Validate every claimed clique with integer squared distances.
        points=ticks[list(indices)];diameter_sq=int(round(float(pdist(points,'sqeuclidean').max())))
        if diameter_sq>conflict_max:raise ValueError('Invalid clique would exclude feasible packings')
        known.add(indices);cliques.append((indices,diameter_sq));return True
    if n:
        # Shifted square covers: diameter sqrt(2)*13 ticks < 19.5 ticks here.
        side=max(1,int(math.floor(math.sqrt(conflict_max/2))))
        stride=max(1,side//3)
        for x in range(int(ticks[:,0].min())-side,int(ticks[:,0].max())+1,stride):
            for y in range(int(ticks[:,1].min())-side,int(ticks[:,1].max())+1,stride):
                add(np.flatnonzero((ticks[:,0]>=x)&(ticks[:,0]<=x+side)&(ticks[:,1]>=y)&(ticks[:,1]<=y+side)))
    if reference is not None and n:
        reference=np.asarray(reference,float)
        if reference.ndim!=2 or reference.shape[1]!=2 or not np.all(np.isfinite(reference)):raise ValueError('Finite reference pairs required')
        objective=np.min(np.sum((ticks[:,None,:]/10-reference[None,:,:])**2,axis=2),axis=1)
    else:objective=np.arange(n)*1e-8
    for iteration in range(max_rounds):
        remaining=time_budget_s-(time.perf_counter()-started)
        if remaining<=0 or n<target:break
        ri=list(np.zeros(n,dtype=int));ci=list(range(n));values=[1.]*n
        for row,(indices,_) in enumerate(cliques,1):
            ri.extend([row]*len(indices));ci.extend(indices);values.extend([1.]*len(indices))
        A=coo_matrix((values,(ri,ci)),shape=(len(cliques)+1,n)).tocsc()
        lower=np.r_[target,np.full(len(cliques),-np.inf)];upper=np.r_[target,np.ones(len(cliques))]
        result=milp(objective,integrality=np.ones(n),bounds=Bounds(0,1),constraints=LinearConstraint(A,lower,upper),
                    options={'time_limit':min(per_solve_s,remaining)})
        row={'round':iteration,'solver_status':int(result.status),'message':str(result.message),'cliques':len(cliques),
             'elapsed_s':time.perf_counter()-started,'new_cuts':0}
        if result.x is not None:
            indices=np.flatnonzero(result.x>.5);selected=ticks[indices];bad=[]
            for i in range(len(indices)):
                for j in range(i):
                    if int(np.sum((selected[i]-selected[j])**2))<=conflict_max:bad.append((i,j))
            row.update(selected_count=len(indices),violating_pairs=len(bad))
            if len(indices)==target and not bad:
                found=(selected/10).tolist();history.append(row);break
            for i,j in bad:
                centre=(selected[i]+selected[j])/2
                ball=np.flatnonzero(np.sum((ticks-centre)**2,axis=1)<limit/4-1e-9)
                if add(ball):row['new_cuts']+=1
                # Always ensure the offending pair is cut even if its disk cut existed.
                if add([indices[i],indices[j]]):row['new_cuts']+=1
        history.append(row)
        if progress:progress({'status':'searching','candidate_count':n,'round':iteration,'cliques':len(cliques),'elapsed_s':time.perf_counter()-started})
        if result.status==2:
            relaxation_infeasible=True;break
        if result.status not in (0,1) or row['new_cuts']==0:break
    return {'algorithm':'Whole-cavity 0.1mm binary point selection, verified clique cuts, bounded MILP',
        'target_wires':target,'candidate_count':n,'grid_step_mm':.1,'grid_origin_mm':[0.,0.],
        'points_radial_tangential_mm':found,'found_grid_packing':found is not None,
        'model_status':'packing_found' if found is not None else 'grid_relaxation_infeasible' if relaxation_infeasible else 'budget_or_solver_unresolved',
        'history':history,'clique_count':len(cliques),'maximum_clique_diameter_squared_ticks':max((v for _,v in cliques),default=0),
        'conflicting_distance_squared_ticks_max':conflict_max,'cliques_validated_with_integer_distances':True,
        'time_budget_s':time_budget_s,'elapsed_s':time.perf_counter()-started,
        'continuous_impossibility_proof':False,'manufacturing_qualified':False}


def build(direct,time_budget_s=30,persist=True):
    direct=Path(direct).resolve();load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    plan=load(direct/'plan.json');mot=Path(plan['source_model']);f=fields(mot);d=dimensions(f)
    if hashlib.sha256(mot.read_bytes()).hexdigest()!=plan['model_sha256']:raise ValueError('Frozen Native model changed')
    previous_path=direct/'continuous_packing_review.json';previous=load(previous_path)
    if previous['candidate_id']!=plan['candidate_id'] or not previous.get('source_files') or any(
        not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest for p,digest in previous.get('source_files',{}).items()):
        raise ValueError('Stale continuous packing source')
    diameter=previous['wire_outer_diameter_mm'];gap=previous['conductor_gap_mm'];wall=previous['wall_clearance_mm']
    geom=mot.parent/'native_geometry.json';region=load(geom)['regions']['Impreg_1']
    ticks=candidate_grid(d,diameter,wall)
    report=solve_grid(ticks,previous['target_wires'],diameter+gap,previous['best']['points_radial_tangential_mm'],time_budget_s,
                      progress=(lambda row:write_json(direct/'whole_grid_progress.json',row)) if persist else None)
    report.update(schema='breadloaf-whole-grid-packing-review-v1',candidate_id=plan['candidate_id'],
        complete_supported_cavity_grid_enumerated=True,wire_outer_diameter_mm=diameter,conductor_gap_mm=gap,wall_clearance_mm=wall,
        independent_native_boundary_check=verify_native_boundary(report['points_radial_tangential_mm'],region,d['beta'],diameter,gap,wall) if report['found_grid_packing'] else None,
        qualified=False,native_winding_updated=False,new_native_fea=0,physical_layer_mapping_confirmed=False,
        source_files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (mot,geom,previous_path)},
        scope='Fixed zero-fillet cavity, insulated wire dimensions, clearances, local radial/tangential grid origin. Does not prove continuous or shifted-grid impossibility.')
    if persist:
        write_json(direct/'whole_grid_packing_review.json',report)
        write_json(direct/'whole_grid_progress.json',{'status':'completed','model_status':report['model_status'],'elapsed_s':report['elapsed_s']})
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);p.add_argument('--time-budget-s',type=float,default=30);a=p.parse_args()
    r=build(a.direct,a.time_budget_s);print(json.dumps({k:v for k,v in r.items() if k not in ('history','source_files')},indent=2))
