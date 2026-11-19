"""Budgeted max-min-clearance packing; independent saved-boundary verification.

Failure to find a feasible set is not an impossibility proof. No Native calls,
phase assignment, winding update, or automatic manufacturing qualification.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from scipy.optimize import minimize
from breadloaf_slot_detail import fields,dimensions
from study_io import write_json
from dimension_grid import resolution_policy


def constraints(points,d,diameter,gap,wall):
    p=np.asarray(points,float);n=len(p);x=p[:,0];y=p[:,1];r=diameter/2
    radius=np.hypot(x,y);c=(d['Tooth_Width']/2+d['Liner_Thickness'])/math.cos(d['beta'])
    rows=[];jac=[]
    for i in range(n):
        for value,gradient in [
            (x[i]-d['body_front_x']-r-wall,[1.,0.]),
            (d['back_R']-d['Liner_Thickness']-radius[i]-r-wall,-p[i]/max(radius[i],1e-15)),
            (x[i]*math.sin(d['beta'])-c*math.cos(d['beta'])+y[i]*math.cos(d['beta'])-r-wall,[math.sin(d['beta']),math.cos(d['beta'])]),
            (x[i]*math.sin(d['beta'])-c*math.cos(d['beta'])-y[i]*math.cos(d['beta'])-r-wall,[math.sin(d['beta']),-math.cos(d['beta'])])]:
            row=np.zeros((n,2));row[i]=gradient;rows.append(value);jac.append(row.ravel())
    for i in range(n):
        for j in range(i):
            delta=p[i]-p[j];dist=np.linalg.norm(delta);unit=delta/max(dist,1e-15)
            row=np.zeros((n,2));row[i]=unit;row[j]=-unit
            rows.append(dist-diameter-gap);jac.append(row.ravel())
    return np.asarray(rows),np.asarray(jac)


def starts(d,target,seed,count):
    rng=np.random.default_rng(seed);front=d['body_front_x'];back=d['back_R']-d['Liner_Thickness'];out=[]
    # Several row counts, then independently jitter each coordinate. These are
    # starting points, not a discretisation of the optimisation variables.
    for k in range(count):
        nr=3+k%3;counts=np.full(nr,target//nr);counts[-(target%nr):]+=1 if target%nr else 0
        if counts.sum()!=target:raise ValueError('Start row count mismatch')
        points=[]
        for row,amount in enumerate(counts):
            x=front+(back-front)*(row+.65)/(nr+.3)
            half=max(.05,(x*math.tan(d['beta'])-(d['Tooth_Width']/2+d['Liner_Thickness'])/math.cos(d['beta']))-.95)
            ys=np.linspace(-half,half,amount) if amount>1 else [0.]
            points.extend([x,y] for y in ys)
        p=np.array(points)
        if k>=3:p+=rng.normal(0,.2+(k%4)*.2,p.shape)
        if k>=6 and k%3==0:
            # Break row topology with farthest-point starts in the cavity.
            candidates=np.c_[rng.uniform(front,back,400),rng.uniform(-6,6,400)]
            mask=(candidates[:,0]*math.tan(d['beta'])-(d['Tooth_Width']/2+d['Liner_Thickness'])/math.cos(d['beta'])-abs(candidates[:,1]))>.5
            candidates=candidates[mask]
            chosen=[int(rng.integers(len(candidates)))];dist=np.full(len(candidates),np.inf)
            for _ in range(target-1):
                dist=np.minimum(dist,np.linalg.norm(candidates-candidates[chosen[-1]],axis=1))
                chosen.append(int(np.argmax(dist)))
            p=candidates[chosen]
        out.append(p)
    return out


def solve(d,target,diameter,gap,wall,restarts=18,maxiter=300,seed=20261105):
    if isinstance(target,bool) or not isinstance(target,int) or target<2:raise ValueError('At least two wires required')
    if not all(math.isfinite(v) for v in (diameter,gap,wall)) or diameter<=0 or min(gap,wall)<0:
        raise ValueError('Positive finite diameter and nonnegative gaps required')
    if any(isinstance(v,bool) or not isinstance(v,int) or v<1 for v in (restarts,maxiter,seed)):
        raise ValueError('Positive integer budgets and seed required')
    started=time.perf_counter();history=[];best=None
    extent=d['back_R']*math.tan(d['beta'])
    bounds=[(d['body_front_x'],d['back_R']-d['Liner_Thickness']),(-extent,extent)]*target+[(-diameter,diameter)]
    def values(z):
        c,_=constraints(z[:-1].reshape(target,2),d,diameter,gap,wall);return c-z[-1]
    def jac(z):
        _,J=constraints(z[:-1].reshape(target,2),d,diameter,gap,wall);return np.c_[J,-np.ones(len(J))]
    objective_gradient=np.r_[np.zeros(2*target),-1.]
    for index,p in enumerate(starts(d,target,seed,restarts)):
        z=np.r_[p.ravel(),min(0,float(constraints(p,d,diameter,gap,wall)[0].min()))]
        result=minimize(lambda z:-z[-1],z,jac=lambda z:objective_gradient,method='SLSQP',bounds=bounds,
                        constraints={'type':'ineq','fun':values,'jac':jac},options={'maxiter':maxiter,'ftol':1e-11})
        points=result.x[:-1].reshape(target,2);c,_=constraints(points,d,diameter,gap,wall);slack=float(c.min())
        history.append({'start':index,'iterations':int(result.nit),'success':bool(result.success),'message':str(result.message),
                        'minimum_constraint_slack_mm':slack,'objective_calls':int(result.nfev)})
        if best is None or slack>best['minimum_constraint_slack_mm']:
            best={'points_radial_tangential_mm':points.tolist(),'minimum_constraint_slack_mm':slack,'start':index}
        if slack>1e-7:break
    return {'algorithm':'SciPy SLSQP multistart max-min physical clearance','target_wires':target,
        'free_coordinate_variables':2*target,'auxiliary_slack_variables':1,'seed':seed,
        'restart_budget':restarts,'iteration_budget_per_start':maxiter,'completed_starts':len(history),'history':history,
        'best':best,'solver_found_nonnegative_slack':best['minimum_constraint_slack_mm']>=0,
        'elapsed_s':time.perf_counter()-started,'failure_is_impossibility_proof':False}


def verify_native_boundary(points,region,beta,diameter,gap,wall):
    """Independent distances to saved line/arc entities, not analytic constraints."""
    p=np.asarray(points,float)
    if p.ndim!=2 or p.shape[1]!=2 or len(p)<2 or not np.all(np.isfinite(p)):raise ValueError('Finite coordinate pairs required')
    if not all(math.isfinite(v) for v in (beta,diameter,gap,wall)) or diameter<=0 or min(gap,wall)<0:raise ValueError('Invalid packing units')
    transform=np.array([[math.cos(beta),math.sin(beta)],[-math.sin(beta),math.cos(beta)]])
    world=p@transform;distances=[];inside=[]
    # This validator accepts the convex line/positive-arc cavity supported here.
    for point in world:
        local_distances=[];conditions=[]
        for e in region['entities']:
            a=np.array([e['start']['x'],e['start']['y']]);b=np.array([e['end']['x'],e['end']['y']])
            if e['type']=='line':
                delta=b-a;projection=np.clip(np.dot(point-a,delta)/np.dot(delta,delta),0,1)
                local_distances.append(float(np.linalg.norm(point-a-projection*delta)))
                offset=point-a
                conditions.append(delta[0]*offset[1]-delta[1]*offset[0]>=-1e-9)
            elif e['type']=='arc' and e['radius']>0:
                centre=np.array([e['centre']['x'],e['centre']['y']]);radius=e['radius']
                start=math.atan2(*(a-centre)[::-1]);end=math.atan2(*(b-centre)[::-1]);angle=math.atan2(*(point-centre)[::-1])
                if (angle-start)%(2*math.pi)<=(end-start)%(2*math.pi)+1e-12:
                    local_distances.append(abs(np.linalg.norm(point-centre)-radius))
                else:local_distances.append(min(np.linalg.norm(point-a),np.linalg.norm(point-b)))
                conditions.append(np.linalg.norm(point-centre)<=radius+1e-9)
            else:raise ValueError('Only convex CCW line/positive-arc Native cavity supported')
        distances.append(min(local_distances));inside.append(all(conditions))
    pairs=np.linalg.norm(world[:,None,:]-world[None,:,:],axis=2);np.fill_diagonal(pairs,np.inf)
    min_pair=float(pairs.min());boundary_slack=float(min(distances)-diameter/2-wall);pair_slack=min_pair-diameter-gap
    return {'whole_wire_centres_inside':all(inside),'minimum_boundary_clearance_mm':float(min(distances)-diameter/2),
            'minimum_centre_distance_mm':min_pair,'boundary_constraint_slack_mm':boundary_slack,
            'pair_constraint_slack_mm':pair_slack,'numerical_tolerance_mm':1e-8,
            'geometrically_verified':all(inside) and min(boundary_slack,pair_slack)>=-1e-8,
            'electrical_assignment_confirmed':False,'manufacturing_qualified':False}


def repair_grid(points,d,diameter,gap,wall,radius_ticks=2,time_limit_s=10.):
    """Select one nearby grid point per wire with binary pair-exclusion MILP."""
    from scipy.optimize import milp,LinearConstraint,Bounds
    from scipy.sparse import coo_matrix
    from breadloaf_conductor_audit import boundary_margin
    if isinstance(radius_ticks,bool) or not isinstance(radius_ticks,int) or not 1<=radius_ticks<=6:
        raise ValueError('Local grid radius 1..6 ticks required')
    if not math.isfinite(time_limit_s) or time_limit_s<=0:raise ValueError('Positive MILP time limit required')
    started=time.perf_counter();points=np.asarray(points,float);candidates=[];groups=[];cost=[]
    if points.ndim!=2 or points.shape[1]!=2 or len(points)<2 or not np.all(np.isfinite(points)):raise ValueError('Finite wire coordinates required')
    for index,point in enumerate(points):
        centre=np.round(point*10).astype(int);offset=np.arange(-radius_ticks,radius_ticks+1)
        a,b=np.meshgrid(offset,offset);grid=(centre+np.c_[a.ravel(),b.ravel()])/10
        grid=grid[boundary_margin(d,grid,diameter)>=wall-1e-10]
        group=[]
        for candidate in grid:
            group.append(len(candidates));candidates.append(candidate);groups.append(index);cost.append(float(np.sum((candidate-point)**2)))
        if not group:return {'found':False,'reason':'A wire has no valid local grid candidate','radius_ticks':radius_ticks,'global_impossibility_proof':False}
    candidates=np.array(candidates);groups=np.array(groups);n=len(candidates);ri=[];ci=[];data=[]
    lower=[];upper=[]
    for wire in range(len(points)):
        indices=np.flatnonzero(groups==wire);row=len(lower)
        ri.extend([row]*len(indices));ci.extend(indices);data.extend([1.]*len(indices));lower.append(1.);upper.append(1.)
    conflicts=0
    for i in range(n):
        other=np.flatnonzero((np.arange(n)>i)&(groups!=groups[i])&(np.linalg.norm(candidates-candidates[i],axis=1)<diameter+gap-1e-10))
        for j in other:
            row=len(lower);ri.extend([row,row]);ci.extend([i,int(j)]);data.extend([1.,1.]);lower.append(-np.inf);upper.append(1.);conflicts+=1
    A=coo_matrix((data,(ri,ci)),shape=(len(lower),n)).tocsc()
    result=milp(np.asarray(cost),integrality=np.ones(n),bounds=Bounds(0,1),
                constraints=LinearConstraint(A,np.asarray(lower),np.asarray(upper)),options={'time_limit':time_limit_s})
    found=result.x is not None and len(np.flatnonzero(result.x>.5))==len(points)
    selected=[]
    if found:
        indices=np.flatnonzero(result.x>.5);indices=indices[np.argsort(groups[indices])];selected=candidates[indices].tolist()
    return {'algorithm':'Local 0.1mm binary assignment with whole-wire bounds and pair exclusions',
        'found':found,'points_radial_tangential_mm':selected,'radius_ticks':radius_ticks,'grid_step_mm':.1,
        'binary_candidates':n,'pair_conflict_constraints':conflicts,'solver_status':int(result.status),
        'solver_message':str(result.message),'time_limit_s':time_limit_s,'elapsed_s':time.perf_counter()-started,
        'global_impossibility_proof':False,'native_winding_updated':False}


def build(direct,persist=True,restarts=18,maxiter=300,diagnostic_grid=False):
    started=time.perf_counter()
    direct=Path(direct).resolve();load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    plan=load(direct/'plan.json');mot=Path(plan['source_model']);snapshot=load(plan['source_snapshot']);f=fields(mot)
    if hashlib.sha256(mot.read_bytes()).hexdigest()!=plan['model_sha256']:raise ValueError('Frozen Native source changed')
    d=dimensions(f);geom=mot.parent/'native_geometry.json';region=load(geom)['regions']['Impreg_1']
    counts=[0]*snapshot['slots']
    for coil in snapshot['coils']:
        for side in ('start','end'):counts[coil[side]]+=coil['turns']*int(f['NumberStrandsHand'])
    if len(set(counts))!=1 or snapshot['paths']!=1:raise ValueError('Uniform one-path winding only')
    diameter=float(f['Wire_Diameter']);gap=float(f['ConductorSeparation']);wall=max(float(f['ConductorsSlotBase']),float(f['ConductorsSlotTooth']))
    result=solve(d,counts[0],diameter,gap,wall,restarts,maxiter)
    points=result['best']['points_radial_tangential_mm'];snapped=(np.round(np.asarray(points)*10)/10).tolist()
    repairs=[]
    if diagnostic_grid and result['solver_found_nonnegative_slack']:
        for radius in (2,4):
            repaired=repair_grid(points,d,diameter,gap,wall,radius)
            if repaired['found']:
                repaired['independent_native_boundary_check']=verify_native_boundary(repaired['points_radial_tangential_mm'],region,d['beta'],diameter,gap,wall)
            repairs.append(repaired)
            if repaired.get('independent_native_boundary_check',{}).get('geometrically_verified'):break
    result.update({'schema':'breadloaf-continuous-packing-review-v1','candidate_id':plan['candidate_id'],
        'coordinate_resolution_policy':resolution_policy(),'grid_repair_required':False,'grid_repair_diagnostic_requested':diagnostic_grid,
        'continuous_solve_elapsed_s':result['elapsed_s'],
        'wire_outer_diameter_mm':diameter,'conductor_gap_mm':gap,'wall_clearance_mm':wall,
        'independent_native_boundary_check':verify_native_boundary(points,region,d['beta'],diameter,gap,wall),
        'grid_0p1mm_points':snapped,'grid_0p1mm_check':verify_native_boundary(snapped,region,d['beta'],diameter,gap,wall),
        'grid_repairs':repairs,'grid_repair_geometrically_verified':any(r.get('independent_native_boundary_check',{}).get('geometrically_verified',False) for r in repairs),
        'qualified':False,'native_winding_updated':False,'new_native_fea':0,'physical_layer_mapping_confirmed':False,
        'source_files':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (mot,geom,Path(plan['source_snapshot']))},
        'policy':'SLSQP success is not physical feasibility; independent line/arc and pair-distance checks govern geometric status. Failure is not impossibility.'})
    result['elapsed_s']=time.perf_counter()-started
    if persist:write_json(direct/'continuous_packing_review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);p.add_argument('--restarts',type=int,default=18);p.add_argument('--maxiter',type=int,default=300)
    a=p.parse_args();r=build(a.direct,restarts=a.restarts,maxiter=a.maxiter)
    print(json.dumps({k:v for k,v in r.items() if k not in ('history','source_files','grid_0p1mm_points')},indent=2))
