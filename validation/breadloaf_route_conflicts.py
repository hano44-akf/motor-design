"""Localise residual route gaps. Witness locations are on polylines, not proofs of cause."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from breadloaf_end_routing import curve_statistics,check_curves
from study_io import write_json


def closest_witness(points_a,points_b):
    a,b=np.asarray(points_a,float),np.asarray(points_b,float)
    if any(p.ndim!=2 or p.shape[1]!=3 or len(p)<2 or not np.all(np.isfinite(p)) for p in (a,b)):
        raise ValueError('Finite 3-D polylines required')
    u=np.diff(a,axis=0)[:,None,:];v=np.diff(b,axis=0)[None,:,:];w=a[:-1,None,:]-b[None,:-1,:]
    A=np.sum(u*u,axis=2);B=np.sum(u*v,axis=2);C=np.sum(v*v,axis=2)
    D=np.sum(u*w,axis=2);E=np.sum(v*w,axis=2)
    sa=np.where(A>0,A,1);sc=np.where(C>0,C,1);zero=np.zeros_like(B);one=np.ones_like(B)
    det=A*C-B*B;valid_det=det>1e-14*np.maximum(A*C,1e-30);safe=np.where(valid_det,det,1)
    s=(B*E-C*D)/safe;t=(A*E-B*D)/safe
    candidates=[(zero,np.clip(E/sc,0,1),np.ones_like(B,dtype=bool)),
                (one,np.clip((E+B)/sc,0,1),np.ones_like(B,dtype=bool)),
                (np.clip(-D/sa,0,1),zero,np.ones_like(B,dtype=bool)),
                (np.clip((B-D)/sa,0,1),one,np.ones_like(B,dtype=bool)),
                (s,t,valid_det&(s>=0)&(s<=1)&(t>=0)&(t<=1))]
    best=None
    for s,t,valid in candidates:
        distance2=np.where(valid,np.sum((w+s[...,None]*u-t[...,None]*v)**2,axis=2),np.inf)
        i,j=np.unravel_index(np.argmin(distance2),distance2.shape);value=float(distance2[i,j])
        if best is None or value<best[0]:best=(value,i,j,float(s[i,j]),float(t[i,j]))
    value,i,j,s,t=best
    return {'distance_mm':float(np.sqrt(max(0,value))),
            'a_t':(i+s)/(len(a)-1),'b_t':(j+t)/(len(b)-1),
            'a_xyz_mm':(a[i]+s*(a[i+1]-a[i])).tolist(),
            'b_xyz_mm':(b[j]+t*(b[j+1]-b[j])).tolist()}


def classify(routes,check,separation):
    by_id={r['id']:r for r in routes}
    if len(by_id)!=len(routes):raise ValueError('Unique route identifiers required')
    stats={r['id']:curve_statistics(r['control_points_xyz_mm'],check['intervals_per_curve']) for r in routes}
    rows=[];groups=Counter();incidents=Counter();coils=Counter()
    for pair in check['nonclear_pairs']:
        a,b=(by_id[pair[k]] for k in ('route_a','route_b'))
        if a['end']!=b['end']:raise ValueError('Pair belongs to different physical ends')
        witness=closest_witness(stats[a['id']]['points'],stats[b['id']]['points'])
        if abs(witness['distance_mm']-pair['polyline_distance_mm'])>1e-8:raise ValueError('Stored clearance distance does not match route geometry')
        same_coil=a['coil_index']==b['coil_index'];same_phase=a['phase']==b['phase']
        relation='same_coil' if same_coil else 'different_coil_same_phase' if same_phase else 'different_phase'
        # Parameter proximity is a location label, not a physical exit-length criterion.
        near_a=min(witness['a_t'],1-witness['a_t'])<=.1
        near_b=min(witness['b_t'],1-witness['b_t'])<=.1
        region='both_near_endpoints' if near_a and near_b else 'one_near_endpoint' if near_a or near_b else 'both_interior'
        pa=np.asarray(a['control_points_xyz_mm'])[[0,-1]];pb=np.asarray(b['control_points_xyz_mm'])[[0,-1]]
        endpoint_distance=float(np.linalg.norm(pa[:,None,:]-pb[None,:,:],axis=2).min())
        endpoint_blocked=endpoint_distance<separation
        row={**pair,'end':a['end'],'relation':relation,'region':region,
             'coil_a':a['coil_index'],'coil_b':b['coil_index'],'phase_a':a['phase'],'phase_b':b['phase'],
             'fixed_endpoint_minimum_distance_mm':endpoint_distance,'fixed_endpoints_below_required_gap':endpoint_blocked,
             'polyline_witness':witness}
        rows.append(row);groups[(a['end'],relation,region,pair['state'])]+=1
        for r in (a,b):incidents[r['id']]+=1
        for coil in {a['coil_index'],b['coil_index']}:coils[coil]+=1
    grouped=[{'end':k[0],'relation':k[1],'region':k[2],'state':k[3],'pairs':v} for k,v in sorted(groups.items())]
    return {'pairs':rows,'groups':grouped,'pair_count':len(rows),
            'by_relation':dict(Counter(r['relation'] for r in rows)),
            'by_region':dict(Counter(r['region'] for r in rows)),
            'by_end':dict(Counter(r['end'] for r in rows)),
            'fixed_endpoint_blocked_pairs':sum(r['fixed_endpoints_below_required_gap'] for r in rows),
            'route_priority':[{'route_id':k,'incident_pairs':v} for k,v in incidents.most_common()],
            'coil_priority':[{'coil_index':k,'incident_pairs':v} for k,v in coils.most_common()]}


def build(direct,persist=True):
    start=time.perf_counter();direct=Path(direct).resolve();source=direct/'route_adjustment_review.json'
    original=json.loads(source.read_text(encoding='utf-8'))
    if not original.get('source_files'):raise ValueError('Frozen route sources required')
    for p,digest in original['source_files'].items():
        if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest:raise ValueError('Route source changed')
    check,_=check_curves(original['routes'],original['required_centre_separation_mm'],original['selected_check']['intervals_per_curve'])
    if check!=original['selected_check']:raise ValueError('Stored route check differs from recomputation')
    summary=classify(original['routes'],check,original['required_centre_separation_mm'])
    result={'schema':'breadloaf-route-conflict-localisation-v1','candidate_id':original['candidate_id'],**summary,
            'confirmed_conflicts':check['confirmed_conflicts'],'unresolved_pairs':check['unresolved_pairs'],
            'source_files':{str(source):hashlib.sha256(source.read_bytes()).hexdigest(),**original['source_files']},
            'location_rule':'Polyline minimum-distance witness; endpoint region means curve parameter within 0.1 of either endpoint. Not a causal or manufacturing classification.',
            'next_action':'Review high-incident coil bundles and endpoint-to-corridor transitions jointly before repeating lateral detours. Preserve phase signs, turns and series paths when proposing reassignment.',
            'end_routing_verified':False,'qualified':False,'used_for_optimization':False,'new_native_fea':0,
            'elapsed_s':time.perf_counter()-start}
    if persist:write_json(direct/'route_conflict_review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);a=p.parse_args();r=build(a.direct)
    print(json.dumps({k:r[k] for k in ('pair_count','by_relation','by_region','by_end','fixed_endpoint_blocked_pairs','elapsed_s')},indent=2))
