"""Unfitted geometry/winding leakage prototype for one-path three-phase coils.

Slot matrix: mu0*l*sum integral m(y)m(y).T/b(y) dy from magnetic energy.
Uniform conductors, infinite-permeability walls, idealised parallel tooth slots.
End: Motor-CAD documented Hanselman formula; no Native inductance is an input.
Physical layer ordering is unknown: scenarios are NOT uncertainty bounds.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import time
import numpy as np
from breadloaf_pwm_preview import csv_number
from study_io import write_json

MU0=4*math.pi*1e-7
SOURCES=[
 'https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/end_winding_inductance_calc.html',
 'https://www.intechopen.com/chapters/71794']


def positive(value,name):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise ValueError('Positive finite '+name+' required')


def hanselman(coils_per_phase,turns,mean_coil_pitch_m,coil_area_m2):
    for key,value in locals().copy().items():positive(value,key)
    argument=mean_coil_pitch_m*math.sqrt(math.pi)/(2*math.sqrt(coil_area_m2))
    if argument<=1:raise ValueError('Hanselman logarithm domain unsupported; no clipping')
    return coils_per_phase*MU0*mean_coil_pitch_m*turns**2/2*math.log(argument)


def slot_energy_matrix(slot_sides,length_m,height_m,width_bottom_m,width_top_m,opening_depth_m,opening_width_m,scenario='mixed',quadrature=32):
    for name,value in [('length',length_m),('height',height_m),('bottom width',width_bottom_m),('top width',width_top_m),('opening width',opening_width_m)]:positive(value,name)
    if not math.isfinite(opening_depth_m) or opening_depth_m<0:raise ValueError('Nonnegative opening depth required')
    if scenario not in ('mixed','listed_bottom_first','listed_top_first'):raise ValueError('Unknown layer scenario')
    if isinstance(quadrature,bool) or not isinstance(quadrature,int) or quadrature<2:raise ValueError('Quadrature at least two required')
    q,w=np.polynomial.legendre.leggauss(quadrature);result=np.zeros((3,3))
    for sides in slot_sides:
        sides=np.asarray(sides,float)
        if sides.ndim!=2 or sides.shape[1]!=3 or not len(sides) or not np.all(np.isfinite(sides)):
            raise ValueError('Finite phase vectors for every slot side required')
        if scenario=='listed_top_first':sides=sides[::-1]
        total=sides.sum(axis=0)
        # Split exactly at layer boundaries before Gaussian integration.
        edges=np.linspace(0,1,len(sides)+1) if scenario!='mixed' else np.array([0.,1.])
        for low,high in zip(edges[:-1],edges[1:]):
            fraction=low+(q+1)*(high-low)/2
            if scenario=='mixed':enclosed=fraction[:,None]*total
            else:
                filled=np.clip(fraction[:,None]*len(sides)-np.arange(len(sides))[None,:],0,1)
                enclosed=filled@sides
            width=width_bottom_m+(width_top_m-width_bottom_m)*fraction
            result+=np.einsum('n,ni,nj->ij',w*(high-low)*height_m/(2*width),enclosed,enclosed)
        result+=opening_depth_m/opening_width_m*np.outer(total,total)
    return MU0*length_m*result


def estimate(snapshot,liner_mm,wire_gap_mm,scenario='mixed'):
    for name,value in [('liner',liner_mm),('wire gap',wire_gap_mm)]:
        if not math.isfinite(value) or value<0:raise ValueError('Nonnegative '+name+' required')
    if snapshot.get('paths')!=1:raise ValueError('One parallel path only; no implicit path scaling')
    slots=snapshot['slots'];coils=snapshot['coils'];g=snapshot['geometry_mm'];sides=[[] for _ in range(slots)]
    if not isinstance(slots,int) or slots<3:raise ValueError('At least three slots required')
    phase_coils=[[] for _ in range(3)]
    for coil in coils:
        phase=coil['phase'];turns=coil['turns'];positive(turns,'coil turns')
        if phase not in (0,1,2) or coil.get('path')!=1:raise ValueError('Three phases / path 1 required')
        if not all(isinstance(coil[k],int) and 0<=coil[k]<slots for k in ('start','end')) or coil['start']==coil['end']:
            raise ValueError('Distinct valid slot indices required')
        vector=np.eye(3)[phase]*turns
        sides[coil['start']].append(vector);sides[coil['end']].append(-vector);phase_coils[phase].append(coil)
    if any(len(s)!=2 for s in sides):raise ValueError('Prototype requires two coil sides per slot')
    if len({len(c) for c in phase_coils})!=1 or not phase_coils[0] or len({c['turns'] for c in coils})!=1:
        raise ValueError('Balanced equal-turn phase coils required for end estimate')
    for key in ('Stator_Bore','Slot_Depth','Tooth_Width','Slot_Opening','Tooth_Tip_Depth','Stator_Lam_Length'):
        positive(g[key],key)
    clearance=liner_mm+wire_gap_mm
    bottom_r=g['Stator_Bore']/2+g['Slot_Depth']-clearance
    top_r=g['Stator_Bore']/2+g['Tooth_Tip_Depth']+clearance
    height=(bottom_r-top_r)/1000
    # Pitch arc minus constant tooth width: explicit geometric approximation.
    bottom_width=(2*math.pi*bottom_r/slots-g['Tooth_Width']-2*clearance)/1000
    top_width=(2*math.pi*top_r/slots-g['Tooth_Width']-2*clearance)/1000
    Lslot=slot_energy_matrix(sides,g['Stator_Lam_Length']/1000,height,bottom_width,top_width,
                             g['Tooth_Tip_Depth']/1000,g['Slot_Opening']/1000,scenario)
    area=height*(bottom_width+top_width)/2
    spans=[min((c['end']-c['start'])%slots,(c['start']-c['end'])%slots) for c in coils]
    if len(set(spans))!=1:raise ValueError('Uniform coil span required')
    pitch=2*math.pi*(bottom_r+top_r)/2/1000*spans[0]/slots
    # Coils share the slot in two radial layers. Exact cuboidal winding area
    # requires the packing geometry; gross trapezoid/2 is only a proxy here.
    end=hanselman(len(phase_coils[0]),coils[0]['turns'],pitch,area/2)
    Q=np.array([[1/math.sqrt(2),1/math.sqrt(6)],[-1/math.sqrt(2),1/math.sqrt(6)],[0,-2/math.sqrt(6)]])
    balanced=Q.T@Lslot@Q
    return {'schema':'breadloaf-geometry-leakage-prototype-v1','scenario':scenario,
            'slot_matrix_H':Lslot.tolist(),'end_diagonal_H':end,
            'combined_matrix_H':(Lslot+np.eye(3)*end).tolist(),
            'slot_mean_self_H':float(np.trace(Lslot)/3),'slot_balanced_mean_H':float(np.trace(balanced)/2),
            'slot_symmetric_energy_min_eigenvalue_H':float(np.linalg.eigvalsh(Lslot).min()),
            'slot_balanced_eigenvalues_H':np.linalg.eigvalsh(balanced).tolist(),
            'geometry_estimates':{'conductor_height_mm':height*1000,'width_bottom_mm':bottom_width*1000,
                 'width_top_mm':top_width*1000,'gross_winding_area_mm2':area*1e6,
                 'coil_area_proxy_mm2':area/2*1e6,'mean_coil_pitch_mm':pitch*1000},
            'qualified':False,'used_for_guidance':False,'sources':SOURCES,
            'limitations':['Parallel-tooth pitch-arc slot approximation, no exact fillet/wedge geometry or magnetic saturation',
                'Uniform conductor distribution; listed layer scenarios are assumptions, not Native layer readback or error bounds',
                'End area from gross winding trapezoid, not a packing/cuboidal geometry solve',
                'No additional differential leakage; possible overlap still requires validation',
                'No skin/proximity/HF correction; diagonal end mutual neglected; no family qualification']}


def build(direct,study,persist=True):
    started=time.perf_counter();direct=Path(direct).resolve();study=Path(study).resolve()
    load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    plan=load(direct/'plan.json');mot=Path(plan['source_model']);raw=mot.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=plan['model_sha256']:raise ValueError('Frozen Native model changed')
    fields={k:v.strip() for k,v in re.findall(r'^([^=\r\n]+)=(.*)$',raw.decode('utf-8',errors='replace'),re.M)}
    if fields.get('Slot_Type')!='Parallel_Tooth' or int(fields.get('WindingLayers','0'))!=2:
        raise ValueError('Parallel-tooth two-layer template required')
    liner=float(fields['Liner_Thickness']);gap=float(fields['Liner_Wire_Gap'])
    candidate=plan['candidate_id'];csv=mot.with_suffix('.csv')
    native_slot,unit,_=csv_number(csv,'Stator Slot Leakage Inductance')
    if unit!='mH':raise ValueError('Native comparison slot unit mismatch')
    native_end,unit,_=csv_number(csv,'Armature End Winding Inductance_(Hanselman)')
    if unit!='mH':raise ValueError('Native comparison end unit mismatch')
    native_pitch,unit,_=csv_number(csv,'Mean Coil Pitch (Used)')
    if unit!='mm':raise ValueError('Native comparison pitch unit mismatch')
    rows=[]
    for finalist in load(study/'result.json')['finalists']:
        snapshot=load(study/(finalist['id']+'_snapshot.json'))
        scenarios=[estimate(snapshot,liner,gap,s) for s in ('mixed','listed_bottom_first','listed_top_first')]
        rows.append({'id':finalist['id'],'scenarios':scenarios,'native_comparison':
            {'slot_effective_H':native_slot*.001,'end_H':native_end*.001,
             'slot_basis_note':'Native equivalent-circuit scalar compared diagnostically with balanced-subspace mean, not phase self',
             'slot_balanced_relative_difference_pct':[100*(s['slot_balanced_mean_H']/(native_slot*.001)-1) for s in scenarios],
             'end_relative_difference_pct':100*(scenarios[0]['end_diagonal_H']/(native_end*.001)-1)} if finalist['id']==candidate else None,
            'qualified':False,'inherited_liner_and_gap_mm':[liner,gap]})
    # Official formula input audit, separate from the independent geometry proxy.
    widths=[float(fields[f'Winding_Cuboid_Width[{i}]']) for i in range(2)]
    heights=[float(fields[f'Winding_Cuboid_Height[{i}]']) for i in range(2)]
    half_slot_layer_area=sum(w*h for w,h in zip(widths,heights))/2
    snapshot=load(plan['source_snapshot'])
    coils_per_phase=sum(c['phase']==0 for c in snapshot['coils'])
    audited=hanselman(coils_per_phase,snapshot['turns_per_coil'],native_pitch/1000,half_slot_layer_area*1e-6)
    result={'schema':'breadloaf-leakage-geometry-review-v1','candidate_id':candidate,'rows':rows,
            'saved_cuboid_diagnostic':{'mean_half_slot_layer_area_mm2':half_slot_layer_area,
                'mean_pitch_used_mm':native_pitch,'calculated_end_H':audited,'native_end_H':native_end*.001,
                'relative_difference_pct':100*(audited/(native_end*.001)-1),
                'scope':'Saved half-slot cuboid interpretation and rounded CSV pitch: input/formula audit only, not independent geometry prediction'},
            'source_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                [mot,csv,study/'result.json']+[study/(r['id']+'_snapshot.json') for r in rows]},
            'qualified':False,'new_native_fea':0,'family_extension_allowed':False,
            'elapsed_s':time.perf_counter()-started,'sources':SOURCES,
            'next_validation':'Resolve physical layer/packing/wedge geometry, then compare other geometries; no automatic optimization penalty yet'}
    if persist:write_json(direct/'leakage_geometry_review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);p.add_argument('--study',required=True);a=p.parse_args()
    r=build(a.direct,a.study)
    print(json.dumps({'elapsed_s':r['elapsed_s'],'saved_cuboid_diagnostic':r['saved_cuboid_diagnostic'],
                      'rows':[{'id':x['id'],'native_comparison':x['native_comparison'],
                               'slot_balanced_uH':[s['slot_balanced_mean_H']*1e6 for s in x['scenarios']],
                               'end_uH':x['scenarios'][0]['end_diagonal_H']*1e6} for x in r['rows']]},indent=2))
