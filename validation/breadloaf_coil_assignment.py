"""Logical coil/turn assignment proposal on verified continuous coordinates.

Preserves the saved slot/phase/sign/turn table. Local radial partition and
Hungarian end pairing are explicit proposals, not read-back physical routing.
Straight end chords are lower bounds, never a manufactured end-turn path.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial import ConvexHull
from breadloaf_packing_selection import select
from native_winding_review import review as native_winding
from study_io import write_json


def envelope(points,diameter):
    p=np.asarray(points,float)
    if p.ndim!=2 or p.shape[1]!=2 or not len(p) or not np.all(np.isfinite(p)) or not math.isfinite(diameter) or diameter<=0:
        raise ValueError('Finite coordinate pairs and positive diameter required')
    p=np.unique(p,axis=0);r=diameter/2
    if len(p)==1:area=0.;perimeter=0.
    elif np.linalg.matrix_rank(p-p[0],tol=1e-10)<2:
        distance=float(np.max(np.linalg.norm(p[:,None,:]-p[None,:,:],axis=2)));area=0.;perimeter=2*distance
    else:
        hull=ConvexHull(p);area=float(hull.volume);perimeter=float(hull.area)
    return {'convex_wire_envelope_area_mm2':area+r*perimeter+math.pi*r*r,
            'axis_aligned_envelope_area_mm2':float(np.prod(np.ptp(p,axis=0)+diameter)),
            'interpretation':'Geometric bundle envelope including voids; not a Native cuboid or a confirmed Hanselman coil area'}


def path_check(nodes,edges):
    if len(set(nodes))!=len(nodes):raise ValueError('Duplicate conductor endpoint nodes')
    incoming={node:[] for node in nodes};outgoing={node:[] for node in nodes}
    for a,b in edges:
        if a not in outgoing or b not in incoming or a==b:raise ValueError('Invalid coil edge')
        outgoing[a].append(b);incoming[b].append(a)
    starts=[n for n in nodes if len(incoming[n])==0];ends=[n for n in nodes if len(outgoing[n])==0]
    if len(starts)!=1 or len(ends)!=1 or any(len(v)>1 for v in incoming.values()) or any(len(v)>1 for v in outgoing.values()):
        return {'single_series_path':False,'visited_nodes':0,'node_count':len(nodes)}
    visited=[];current=starts[0]
    while current not in visited:
        visited.append(current)
        if not outgoing[current]:break
        current=outgoing[current][0]
    return {'single_series_path':len(visited)==len(nodes) and current==ends[0],
            'visited_nodes':len(visited),'node_count':len(nodes),'start_terminal':starts[0],'end_terminal':ends[0]}


def assign(snapshot,points,wire_diameter,copper_diameter):
    points=np.asarray(points,float);coils=snapshot['coils'];q=snapshot['slots']
    if snapshot['paths']!=1 or points.ndim!=2 or points.shape[1]!=2 or not np.all(np.isfinite(points)):
        raise ValueError('Finite packing / one-path prototype required')
    if not 0<copper_diameter<=wire_diameter or not math.isfinite(wire_diameter):raise ValueError('Positive copper and insulation dimensions required')
    slots=[[] for _ in range(q)]
    for index,c in enumerate(coils):
        if isinstance(c['phase'],bool) or c['phase'] not in (0,1,2) or c['path']!=1 or isinstance(c['turns'],bool) or not isinstance(c['turns'],int) or c['turns']<1:
            raise ValueError('Three phase, path 1, positive integer coil turns required')
        if not all(isinstance(c[k],int) and 0<=c[k]<q for k in ('start','end')) or c['start']==c['end']:
            raise ValueError('Valid distinct coil slots required')
        slots[c['start']].append((index,1,c['turns']));slots[c['end']].append((index,-1,c['turns']))
    if any(sum(side[2] for side in slot)!=len(points) for slot in slots):raise ValueError('Packing count does not match slot turn count')
    if len(np.unique(points,axis=0))!=len(points):raise ValueError('Duplicate packing centres')
    rank=np.lexsort((points[:,1],points[:,0]));records=[];by_side={}
    # Each slot uses the same point set. Native coil-list order selects the
    # proposed inner/outer group; this does not assert actual Native layers.
    for slot,sides in enumerate(slots):
        offset=0;angle=(slot+.5)*2*math.pi/q;cs=math.cos(angle);sn=math.sin(angle)
        for coil_index,sign,count in sides:
            group=[]
            for point_index in rank[offset:offset+count]:
                radial,tangent=points[point_index];world=[float(radial*cs-tangent*sn),float(radial*sn+tangent*cs)]
                row={'id':f's{slot}_p{int(point_index)}','slot_zero_based':slot,'point_index':int(point_index),
                     'coil_index':coil_index,'phase':coils[coil_index]['phase'],'path':1,'axial_direction':sign,
                     'radial_mm':float(radial),'tangential_mm':float(tangent),'world_xy_mm':world}
                records.append(row);group.append(row)
            by_side[(coil_index,sign)]=group;offset+=count
    signed_counts=np.zeros((q,3),int);expected=np.zeros((q,3),int)
    for r in records:signed_counts[r['slot_zero_based'],r['phase']]+=r['axial_direction']
    for c in coils:expected[c['start'],c['phase']]+=c['turns'];expected[c['end'],c['phase']]-=c['turns']
    if not np.array_equal(signed_counts,expected):raise ValueError('Assigned ampere-conductors changed source winding')
    rows=[]
    for index,c in enumerate(coils):
        go=by_side[(index,1)];back=by_side[(index,-1)]
        cost=np.linalg.norm(np.array([r['world_xy_mm'] for r in go])[:,None,:]-np.array([r['world_xy_mm'] for r in back])[None,:,:],axis=2)
        a,b=linear_sum_assignment(cost);pairing=dict(zip(map(int,a),map(int,b)));nodes=[];edges=[];ends=[]
        for turn in range(c['turns']):
            start=go[turn];returned=back[pairing[turn]]
            for row in (start,returned):row['turn_in_coil_zero_based']=turn
            for row in (start,returned):nodes.extend([row['id']+'_front',row['id']+'_rear'])
            edges.extend([(start['id']+'_front',start['id']+'_rear'),(returned['id']+'_rear',returned['id']+'_front')])
            edges.append((start['id']+'_rear',returned['id']+'_rear'))
            ends.append({'end':'rear','from_conductor':start['id'],'to_conductor':returned['id'],
                         'straight_chord_lower_bound_mm':float(cost[turn,pairing[turn]])})
            if turn<c['turns']-1:
                next_start=go[turn+1];edges.append((returned['id']+'_front',next_start['id']+'_front'))
                ends.append({'end':'front','from_conductor':returned['id'],'to_conductor':next_start['id'],
                             'straight_chord_lower_bound_mm':float(np.linalg.norm(np.array(returned['world_xy_mm'])-next_start['world_xy_mm']))})
        graph=path_check(nodes,edges)
        if not graph['single_series_path']:raise ValueError('Coil proposal has a broken/branched turn graph')
        bundles=[envelope([[r['radial_mm'],r['tangential_mm']] for r in group],wire_diameter) for group in (go,back)]
        rows.append({'coil_index':index,'phase':'ABC'[c['phase']],'turns':c['turns'],'start_slot_zero_based':c['start'],'return_slot_zero_based':c['end'],
            'logical_path_check':graph,'active_conductor_segments':2*c['turns'],'end_connections':ends,
            'sum_end_chord_lower_bound_mm':sum(e['straight_chord_lower_bound_mm'] for e in ends),
            'bundle_geometry':bundles,'copper_area_per_coil_side_mm2':c['turns']*math.pi*(copper_diameter/2)**2,
            'insulated_wire_area_per_coil_side_mm2':c['turns']*math.pi*(wire_diameter/2)**2,
            'end_routing_verified':False})
    harmonic_order=snapshot['poles']//2;angles=np.arange(q)*2*math.pi/q
    phasors=np.exp(1j*harmonic_order*angles)@signed_counts
    counts=np.array([sum(r['phase']==phase for r in records) for phase in range(3)])
    kw=np.abs(phasors)/counts
    return {'conductors':records,'coils':rows,'signed_slot_phase_counts':signed_counts.tolist(),
            'conductor_count':len(records),'slot_counts':[sum(r['slot_zero_based']==s for r in records) for s in range(q)],
            'phase_counts':counts.tolist(),'slot_lumped_fundamental_winding_factors':kw.tolist(),
            'logical_assignment_verified':True,'physical_layer_mapping_confirmed':False,
            'assignment_method':'Proposed local radial rank partition in saved coil-list order; minimum-chord return pairing',
            'phase_series_coil_order_verified':False,'end_routing_verified':False,'conductor_derived_end_area_mm2':None}


def build(direct,persist=True):
    started=time.perf_counter();direct=Path(direct).resolve();load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    selected_path=direct/'selected_continuous_packing.json';selected=load(selected_path)
    for p,digest in selected.get('source_files',{}).items():
        if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest:raise ValueError('Selected packing source changed')
    # Recheck geometry instead of trusting the stored passed flag.
    rechecked=select(direct,persist=False)
    if selected['candidate_id']!=rechecked['candidate_id'] or selected['points_radial_tangential_mm']!=rechecked['points_radial_tangential_mm']:
        raise ValueError('Selected coordinates differ from independently verified source')
    plan=load(direct/'plan.json');snapshot_path=Path(plan['source_snapshot']);snapshot=load(snapshot_path);mot=Path(plan['source_model'])
    if hashlib.sha256(snapshot_path.read_bytes()).hexdigest()!=plan['snapshot_sha256']:raise ValueError('Frozen winding snapshot changed')
    native=native_winding(mot)
    if native['coils']!=snapshot['coils']:raise ValueError('Snapshot/Native coil table mismatch')
    # Read geometry inputs only, not Native inductance output.
    from breadloaf_slot_detail import fields
    f=fields(mot)
    if int(f['NumberStrandsHand'])!=1:raise ValueError('Single strand prototype only')
    assigned=assign(snapshot,selected['points_radial_tangential_mm'],float(f['Wire_Diameter']),float(f['Copper_Diameter']))
    if not np.allclose(assigned['slot_lumped_fundamental_winding_factors'],native['fundamental_winding_factors'],rtol=0,atol=1e-12):
        raise ValueError('Source winding factor changed')
    report={'schema':'breadloaf-coil-coordinate-proposal-v1','candidate_id':selected['candidate_id'],**assigned,
            'geometric_packing_verified':True,'native_winding_factors':native['fundamental_winding_factors'],
            'native_winding_updated':False,'qualified':False,'new_native_fea':0,'elapsed_s':time.perf_counter()-started,
            'source_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (selected_path,snapshot_path,mot)},
            'pending_checks':['physical layer/phase insulation and assignment choice','3D end routing/crossing/axial clearance',
                              'phase coil interconnections and terminal routing','cuboid construction and end-inductance area definition',
                              'effects of proposed packing/routing on performance'],
            'scope':'Logical turn connectivity and signed slot ampere-conductors verified; physical routing/manufacturing and end-inductance not qualified. Chords are lower bounds only.'}
    if persist:write_json(direct/'coil_coordinate_proposal.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);a=p.parse_args();r=build(a.direct)
    print(json.dumps({k:r[k] for k in ('candidate_id','conductor_count','slot_counts','phase_counts','slot_lumped_fundamental_winding_factors','logical_assignment_verified','physical_layer_mapping_confirmed','elapsed_s','new_native_fea')},indent=2))
