"""Offline audit of saved conductor centres and geometric packing evidence.

Saved arrays can contain stale/inactive cells. Boundary-compatible points do not
establish electrical phase/layer mapping. A new lattice is independent geometry
evidence only, never a Native winding update or a manufacturing qualification.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import time
import numpy as np
from breadloaf_slot_detail import fields,dimensions,wall_halfwidth
from breadloaf_leakage_geometry import hanselman
from breadloaf_pwm_preview import csv_number
from study_io import write_json


def boundary_margin(d,points,wire_diameter_mm):
    points=np.asarray(points,float)
    if points.ndim!=2 or points.shape[1]!=2 or not np.all(np.isfinite(points)):
        raise ValueError('Finite radial/tangential point pairs required')
    if isinstance(wire_diameter_mm,bool) or not math.isfinite(wire_diameter_mm) or wire_diameter_mm<=0:
        raise ValueError('Positive insulated wire diameter required')
    x=points[:,0];y=points[:,1];liner=d['Liner_Thickness']
    return np.minimum.reduce([x-d['body_front_x'],d['back_R']-liner-np.hypot(x,y),
        (wall_halfwidth(d,x,liner)-abs(y))*math.cos(d['beta'])])-wire_diameter_mm/2


def extract_saved(f,d):
    rows=[];tables=[];zero_count=0
    diameter=float(f['Wire_Diameter'])
    for side in ('L','R'):
        long='Left' if side=='L' else 'Right';all_points=[]
        for key,value in f.items():
            m=re.fullmatch(r'ConductorCentre_'+side+r'_x\[(\d+)\]\[(\d+)\]',key)
            if not m:continue
            col,row=map(int,m.groups());other=f'ConductorCentre_{side}_y[{col}][{row}]'
            if other not in f:raise ValueError('Conductor centre coordinate pair missing')
            # Saved winding-editor coordinates: y radial and x tangential.
            # This frame is a case-specific geometric interpretation, not an API enum declaration.
            point=[float(f[other]),float(value)]
            if point==[0.,0.]:zero_count+=1;continue
            margin=float(boundary_margin(d,[point],diameter)[0])
            all_points.append({'side':side,'column':col,'row':row,'radial_mm':point[0],
                'tangential_mm':point[1],'wire_boundary_margin_mm':margin,'whole_wire_inside':margin>=-1e-9})
        for key,value in f.items():
            m=re.fullmatch(r'Rows_'+long+r'\[(\d+)\]',key)
            if m:
                col=int(m.group(1));count=int(value);missing=int(f[f'Missing_Rows_{long}[{col}]'])
                tables.append({'side':side,'column':col,'declared_rows':count,'missing_rows':missing})
        rows.extend(all_points)
    return {'coordinate_frame':'saved y interpreted as radial, x as tangential; checked against slot boundaries',
        'points':rows,'zero_padding_count':zero_count,'placement_table':tables,
        'nonzero_saved_point_count':len(rows),'boundary_compatible_raw_count':sum(p['whole_wire_inside'] for p in rows),
        'outside_whole_wire_count':sum(not p['whole_wire_inside'] for p in rows),
        'declared_placement_count':sum(t['declared_rows'] for t in tables),
        'active_mask_confirmed':False,'phase_and_layer_mapping_confirmed':False}


def lattice_packing(d,diameter,target,gap_mm,wall_clearance_mm,offset_steps=12):
    """Bounded hexagonal-lattice search, no proof of optimal packing on failure."""
    if not isinstance(target,int) or isinstance(target,bool) or target<=0:raise ValueError('Positive target wire count required')
    if not all(math.isfinite(v) for v in (diameter,gap_mm,wall_clearance_mm)) or diameter<=0 or min(gap_mm,wall_clearance_mm)<0:
        raise ValueError('Finite positive diameter and nonnegative clearances required')
    if isinstance(offset_steps,bool) or not isinstance(offset_steps,int) or not 1<=offset_steps<=32:raise ValueError('Offset steps 1..32 required')
    pitch=diameter+gap_mm;best=np.empty((0,2));evaluations=0
    # Centred coordinates, then rotate the lattice; don't rotate the slot.
    extent=d['back_R']-d['body_front_x']+2*float(wall_halfwidth(d,d['back_R']))
    count=math.ceil(extent/pitch)+2
    indices=np.arange(-count,count+1);ii,jj=np.meshgrid(indices,indices)
    local=np.c_[(ii+jj/2).ravel()*pitch,jj.ravel()*pitch*math.sqrt(3)/2]
    origin=np.array([(d['body_front_x']+d['back_R']-d['Liner_Thickness'])/2,0.])
    for degrees in (0.,15.,30.,45.,60.,75.):
        angle=math.radians(degrees);rotation=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
        for a in range(offset_steps):
            for b in range(offset_steps):
                phase=np.array([a/offset_steps*pitch,b/offset_steps*pitch*math.sqrt(3)/2])
                points=(local+phase)@rotation.T+origin
                valid=points[boundary_margin(d,points,diameter)>=wall_clearance_mm-1e-10];evaluations+=1
                if len(valid)>len(best):best=valid
    selected=best[np.argsort(-best[:,0])][:target]
    if len(selected)>1:
        distances=np.linalg.norm(selected[:,None,:]-selected[None,:,:],axis=2);np.fill_diagonal(distances,np.inf)
        minimum=float(distances.min())
    else:minimum=None
    margin=float(boundary_margin(d,selected,diameter).min()) if len(selected) else None
    return {'algorithm':'Bounded hexagonal lattice orientations and translations; no FEA or global packing proof',
            'requested_wires':target,'best_lattice_wire_count':len(best),'selected_wire_count':len(selected),
            'geometric_target_found':len(selected)==target,'points_radial_tangential_mm':selected.tolist(),
            'minimum_centre_separation_mm':minimum,'required_centre_separation_mm':pitch,
            'minimum_wire_boundary_margin_mm':margin,'required_wall_clearance_mm':wall_clearance_mm,
            'placements_checked':evaluations,'electrical_assignment_confirmed':False,
            'native_winding_updated':False,'manufacturing_qualified':False,
            'failure_is_impossibility_proof':False}


def build(direct,persist=True):
    started=time.perf_counter();direct=Path(direct).resolve();load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    plan=load(direct/'plan.json');mot=Path(plan['source_model']);snapshot=load(plan['source_snapshot'])
    if hashlib.sha256(mot.read_bytes()).hexdigest()!=plan['model_sha256']:raise ValueError('Frozen source model changed')
    f=fields(mot);d=dimensions(f);saved=extract_saved(f,d);csv=mot.with_suffix('.csv')
    if f.get('Wedge_Model')!='Wedge' or f.get('Armature_CoilStyle')!='0':
        raise ValueError('Nonconducting wedge / round stranded-wire prototype only')
    if snapshot['paths']!=1 or int(f['ParallelPaths'])!=1:raise ValueError('One-path prototype only')
    strands=int(f['NumberStrandsHand']);counts=[0]*snapshot['slots']
    for coil in snapshot['coils']:
        for k in ('start','end'):counts[coil[k]]+=coil['turns']*strands
    if len(set(counts))!=1:raise ValueError('Nonuniform slot wire counts require slot-specific geometry review')
    target=counts[0];diameter=float(f['Wire_Diameter']);gap=float(f['ConductorSeparation'])
    wall_clearance=max(float(f['ConductorsSlotBase']),float(f['ConductorsSlotTooth']))
    packing=lattice_packing(d,diameter,target,gap,wall_clearance)
    # The cuboid subdivisions are input to the documented end formula, not an electrical layer-order mask.
    cuboids=[{'width_mm':float(f[f'Winding_Cuboid_Width[{i}]']),
              'height_mm':float(f[f'Winding_Cuboid_Height[{i}]'])} for i in range(int(f['NumberOfCuboids']))]
    documented_area=sum(c['width_mm']*c['height_mm'] for c in cuboids)/int(f['WindingLayers'])
    pitch,pitch_unit,_=csv_number(csv,'Mean Coil Pitch (Used)');native_end,end_unit,_=csv_number(csv,'Armature End Winding Inductance_(Hanselman)')
    if pitch_unit!='mm' or end_unit!='mH':raise ValueError('End comparison units mismatch')
    calculated=hanselman(sum(c['phase']==0 for c in snapshot['coils']),snapshot['turns_per_coil'],pitch*.001,documented_area*1e-6)
    result={'schema':'breadloaf-conductor-coordinate-audit-v1','candidate_id':plan['candidate_id'],
        'required_wires_per_slot':target,'wire_outer_diameter_mm':diameter,'saved_coordinates':saved,
        'saved_coordinates_match_required_count':saved['boundary_compatible_raw_count']==target and saved['declared_placement_count']==target,
        'new_geometric_packing':packing,'physical_layer_mapping_confirmed':False,
        'end_input_audit':{'cuboids':cuboids,'sum_saved_cuboid_area_mm2':documented_area*int(f['WindingLayers']),
            'winding_layers_input':int(f['WindingLayers']),'formula_coil_area_mm2':documented_area,
            'formula_policy':'Sum saved cuboid width*height, divided by WindingLayers input; not physical conductor phase assignment',
            'used_saved_native_geometry_inputs':True,'independent_new_geometry_prediction':False,
            'calculated_end_H':calculated,'native_end_H':native_end*.001,
            'relative_difference_pct':100*(calculated/(native_end*.001)-1)},
        'conductor_derived_end_area_mm2':None,'qualified':False,'used_for_guidance':False,'new_native_fea':0,
        'elapsed_s':time.perf_counter()-started,
        'source_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (mot,csv,Path(plan['source_snapshot']))},
        'policy':'Do not treat all nonzero saved cells as active wires; do not infer electrical layers from cuboids or select an end area by result matching.',
        'next_action':'Resolve active coordinate generation and coil-to-position assignment. Native EM completion does not establish packing validity.'}
    if persist:write_json(direct/'conductor_coordinate_review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);a=p.parse_args();r=build(a.direct)
    print(json.dumps({'required_wires':r['required_wires_per_slot'],'saved_counts':
        {k:r['saved_coordinates'][k] for k in ('nonzero_saved_point_count','boundary_compatible_raw_count','declared_placement_count')},
        'new_packing':r['new_geometric_packing'],'end_input_audit':r['end_input_audit'],'elapsed_s':r['elapsed_s']},indent=2))
