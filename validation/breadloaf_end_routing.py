"""Low-cost smooth end-turn proposal with bounded curve-clearance checks.

Greedy colouring separates planar chord conflicts by proposed arch heights.
Full 3-D curve checks can still fail; colouring is not routing certification.
No terminal/phase interconnect routes or actual housing clearance are solved.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from breadloaf_slot_detail import fields
from breadloaf_pwm_preview import csv_number
from dimension_grid import mm
from study_io import write_json


def segment_distance(a,b,c,d):
    """Minimum distance between two polyline segment sets, in any dimension.

    Minimise the convex quadratic over [0,1]^2: four box edges plus the
    unconstrained stationary point when it lies inside. Handles degenerate ends.
    """
    a,b,c,d=map(lambda v:np.asarray(v,float),(a,b,c,d))
    if a.ndim!=2 or a.shape!=b.shape or c.ndim!=2 or c.shape!=d.shape or a.shape[1]!=c.shape[1] or not all(np.all(np.isfinite(v)) for v in (a,b,c,d)):
        raise ValueError('Aligned finite segment endpoint arrays required')
    u=(b-a)[:,None,:];v=(d-c)[None,:,:];w=a[:,None,:]-c[None,:,:]
    A=np.sum(u*u,axis=2);B=np.sum(u*v,axis=2);C=np.sum(v*v,axis=2)
    D=np.sum(u*w,axis=2);E=np.sum(v*w,axis=2)
    def distance(s,t):return np.sum((w+s[...,None]*u-t[...,None]*v)**2,axis=2)
    safeA=np.where(A>0,A,1);safeC=np.where(C>0,C,1)
    zero=np.zeros_like(B);one=np.ones_like(B)
    result=np.minimum.reduce([distance(zero,np.clip(E/safeC,0,1)),distance(one,np.clip((E+B)/safeC,0,1)),
                              distance(np.clip(-D/safeA,0,1),zero),distance(np.clip((B-D)/safeA,0,1),one)])
    determinant=A*C-B*B;safe=np.where(determinant>1e-14*np.maximum(A*C,1e-30),determinant,1)
    s=(B*E-C*D)/safe;t=(A*E-B*D)/safe
    valid=(determinant>1e-14*np.maximum(A*C,1e-30))&(s>=0)&(s<=1)&(t>=0)&(t<=1)
    return float(np.sqrt(np.maximum(0,np.min(np.where(valid,np.minimum(result,distance(s,t)),result)))))


def bezier(control,t,derivative=0):
    P=np.asarray(control,float);t=np.asarray(t,float).reshape(-1,1)
    if P.ndim!=2 or P.shape[1]!=3 or len(P)<3 or not np.all(np.isfinite(P)) or not np.all(np.isfinite(t)):raise ValueError('Finite 3D Bezier controls required')
    if derivative not in (0,1,2):raise ValueError('Derivative 0..2 required')
    for _ in range(derivative):P=(len(P)-1)*np.diff(P,axis=0)
    degree=len(P)-1
    weights=np.hstack([math.comb(degree,k)*(1-t)**(degree-k)*t**k for k in range(degree+1)])
    return weights@P


def arch(a,b,peak_height):
    if not math.isfinite(peak_height) or peak_height<=0:raise ValueError('Positive peak height required')
    a=np.r_[np.asarray(a,float),0.];b=np.r_[np.asarray(b,float),0.]
    return np.array([a,a+[0,0,4*peak_height/3],b+[0,0,4*peak_height/3],b])


def colour_conflicts(edges,separation):
    neighbours=[set() for _ in edges]
    for i,e in enumerate(edges):
        for j in range(i):
            f=edges[j]
            if segment_distance([e['a']],[e['b']],[f['a']],[f['b']])<separation:
                neighbours[i].add(j);neighbours[j].add(i)
    colours={}
    while len(colours)<len(edges):
        remaining=set(range(len(edges)))-colours.keys()
        node=max(remaining,key=lambda i:(len({colours[j] for j in neighbours[i] if j in colours}),len(neighbours[i]),-i))
        used={colours[j] for j in neighbours[node] if j in colours};colour=0
        while colour in used:colour+=1
        colours[node]=colour
    return [colours[i] for i in range(len(edges))],sum(map(len,neighbours))//2


def curve_statistics(control,intervals):
    if isinstance(intervals,bool) or not isinstance(intervals,int) or intervals<4:raise ValueError('At least four curve intervals required')
    t=np.linspace(0,1,intervals+1);points=bezier(control,t)
    P=np.asarray(control,float);degree=len(P)-1
    # The derivative curve lies in the convex hull of its derivative controls.
    # Unlike an endpoint sample, this is valid for the higher-degree detours too.
    second=degree*(degree-1)*np.diff(P,n=2,axis=0)
    bound=float(np.linalg.norm(second,axis=1).max()/(8*intervals**2))
    q,w=np.polynomial.legendre.leggauss(48)
    length=float(np.sum(w*np.linalg.norm(bezier(control,(q+1)/2,1),axis=1))/2)
    d1=bezier(control,t,1);d2=bezier(control,t,2);speed=np.linalg.norm(d1,axis=1)
    curvature=np.linalg.norm(np.cross(d1,d2),axis=1)/speed**3
    return {'points':points,'linearisation_error_bound_mm':bound,'length_mm':length,
            'sampled_minimum_bend_radius_mm':float(1/curvature.max()) if curvature.max()>0 else None}


def check_curves(routes,separation,intervals):
    stats=[curve_statistics(np.array(r['control_points_xyz_mm']),intervals) for r in routes];pairs=[]
    for i,s in enumerate(stats):
        for j in range(i):
            other=stats[j]
            if routes[i]['end']!=routes[j]['end']:continue
            error=s['linearisation_error_bound_mm']+other['linearisation_error_bound_mm']
            box_distance=np.linalg.norm(np.maximum(0,np.maximum(s['points'].min(axis=0)-other['points'].max(axis=0),other['points'].min(axis=0)-s['points'].max(axis=0))))
            if box_distance-error>=separation:continue
            distance=segment_distance(s['points'][:-1],s['points'][1:],other['points'][:-1],other['points'][1:])
            lower=max(0,distance-error);upper=distance+error
            state='confirmed_curve_conflict' if upper<separation else 'clear_with_error_bound' if lower>=separation else 'unresolved_near_limit'
            if state!='clear_with_error_bound':pairs.append({'route_a':routes[i]['id'],'route_b':routes[j]['id'],
                'polyline_distance_mm':distance,'distance_lower_bound_mm':lower,'distance_upper_bound_mm':upper,'state':state})
    return {'intervals_per_curve':intervals,'checked_end_routes':len(routes),
            'confirmed_conflicts':sum(p['state']=='confirmed_curve_conflict' for p in pairs),
            'unresolved_pairs':sum(p['state']=='unresolved_near_limit' for p in pairs),
            'nonclear_pairs':pairs,'maximum_curve_linearisation_bound_mm':max(s['linearisation_error_bound_mm'] for s in stats),
            'all_modelled_routes_clear':not pairs},stats


def build(direct,persist=True,intervals=32):
    started=time.perf_counter();direct=Path(direct).resolve();load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    proposal_path=direct/'coil_coordinate_proposal.json';proposal=load(proposal_path)
    if not proposal.get('logical_assignment_verified') or not proposal.get('source_files'):raise ValueError('Verified logical assignment required')
    for path,digest in proposal['source_files'].items():
        if not Path(path).is_file() or hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest:raise ValueError('Coil proposal source changed')
    from breadloaf_coil_assignment import build as recheck_assignment
    fresh=recheck_assignment(direct,persist=False)
    if proposal['conductors']!=fresh['conductors'] or proposal['coils']!=fresh['coils']:raise ValueError('Coil assignment proposal changed')
    plan=load(direct/'plan.json');mot=Path(plan['source_model']);f=fields(mot)
    if proposal['candidate_id']!=plan['candidate_id']:raise ValueError('Candidate mismatch')
    diameter=float(f['Wire_Diameter']);gap=float(f['ConductorSeparation']);separation=diameter+gap
    copper=float(f['Copper_Diameter']);rho=float(f['StatorConductor_ResistivityAt20C']);length=float(f['Stator_Lam_Length'])
    if not all(math.isfinite(v) and v>0 for v in (diameter,separation,copper,rho,length)):raise ValueError('Positive physical inputs required')
    records={r['id']:r for r in proposal['conductors']};routes=[];end_summaries=[]
    base=mm(diameter/2+max(float(f['ConductorsSlotBase']),float(f['ConductorsSlotTooth'])),up=True);height_step=mm(separation,up=True)
    for end in ('front','rear'):
        edges=[]
        for coil in proposal['coils']:
            for connection in coil['end_connections']:
                if connection['end']==end:edges.append({'a':records[connection['from_conductor']]['world_xy_mm'],
                    'b':records[connection['to_conductor']]['world_xy_mm'],'coil_index':coil['coil_index'],
                    'phase':coil['phase'],'from_conductor':connection['from_conductor'],'to_conductor':connection['to_conductor']})
        colours,conflicts=colour_conflicts(edges,separation)
        for index,(edge,colour) in enumerate(zip(edges,colours)):
            peak=base+height_step*colour
            control=arch(edge['a'],edge['b'],peak);world=control.copy()
            world[:,2]=(-length/2-control[:,2]) if end=='front' else length/2+control[:,2]
            routes.append({'id':end+'_'+str(index),'end':end,'colour_level':colour,'proposed_peak_height_mm':peak,
                           **edge,'control_points_xyz_mm':control.tolist(),'control_points_world_xyz_mm':world.tolist()})
        end_summaries.append({'end':end,'connection_count':len(edges),'planar_chord_conflict_pairs':conflicts,
                             'greedy_colour_levels':max(colours)+1,'proposed_axial_extent_with_wire_mm':base+height_step*max(colours)+diameter/2,
                             'available_axial_space_mm':None,'housing_clearance_verified':False})
    check,stats=check_curves(routes,separation,intervals)
    for route,stat in zip(routes,stats):
        route.update(length_mm=stat['length_mm'],sampled_minimum_bend_radius_mm=stat['sampled_minimum_bend_radius_mm'])
    phases=[]
    for phase in 'ABC':
        active=sum(r['phase']==ord(phase)-65 for r in records.values())*length
        end_length=sum(r['length_mm'] for r in routes if r['phase']==phase)
        phases.append({'phase':phase,'active_length_mm':active,'modelled_end_length_mm':end_length,
                       'partial_phase_length_mm':active+end_length,'partial_R20_ohm':rho*(active+end_length)/1000/(math.pi*(copper/2000)**2),
                       'omits_intercoil_links_and_terminals':True,'applied_phase_resistance_ohm':None})
    native_R,unit,_=csv_number(mot.with_suffix('.csv'),'Phase Resistance')
    if unit!='Ohms':raise ValueError('Native resistance unit mismatch')
    result={'schema':'breadloaf-end-routing-prototype-v1','candidate_id':proposal['candidate_id'],'route_count':len(routes),
            'model_status':'spacing_violations_in_proposal' if check['confirmed_conflicts'] else 'near_limit_unresolved' if check['unresolved_pairs'] else 'modelled_curves_clear_other_checks_pending',
            'used_for_optimization':False,'resistance_estimate_valid_for_design':False,
            'routes':routes,'ends':end_summaries,'curve_clearance_check':check,'phase_length_diagnostics':phases,
            'base_peak_height_mm':base,'colour_height_step_mm':height_step,'wire_outer_diameter_mm':diameter,'required_centre_separation_mm':separation,
            'coordinate_convention':'XY world slot coordinates; local Z outwards from each lamination face. Separate world XYZ controls place front at -stack/2 and rear at +stack/2.',
            'native_saved_phase_resistance_ohm':native_R,'resistivity_at_20C_ohm_m':rho,
            'end_routing_verified':False,'conductor_derived_end_area_mm2':None,'end_inductance_H':None,
            'native_winding_updated':False,'qualified':False,'new_native_fea':0,'elapsed_s':time.perf_counter()-started,
            'source_files':{str(p):hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (proposal_path,mot,mot.with_suffix('.csv'))},
            'scope':'Smooth cubic arch geometry diagnostic, not a routed/manufacturable winding. Greedy heights are a proposal, not minimum required space.',
            'pending_checks':['resolve curve conflicts and near-limit pairs','terminals and intercoil routes/stubs','housing/rotor radial and axial exclusion volumes',
                              'minimum bend-radius requirement and continuous-curve extrema','phase insulation and routing sequence','cuboid/end-area generation after routing']}
    if persist:write_json(direct/'end_routing_review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);p.add_argument('--intervals',type=int,default=32);a=p.parse_args()
    r=build(a.direct,intervals=a.intervals)
    print(json.dumps({'route_count':r['route_count'],'ends':r['ends'],
         'curve_check':{k:v for k,v in r['curve_clearance_check'].items() if k!='nonclear_pairs'},
         'phase_diagnostics':r['phase_length_diagnostics'],'elapsed_s':r['elapsed_s']},indent=2))
