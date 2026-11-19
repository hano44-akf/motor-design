"""Parallel-tooth slot geometry with circular base and explicit tip taper.

This reconstructs supported zero-fillet slot geometry from dimensions, then
checks saved Native boundaries. No inductance fitting or new Native solve.
Physical electrical coil layers are distinct from thermal cuboid subdivisions.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import time
import numpy as np
from scipy.integrate import quad
from breadloaf_leakage_geometry import MU0,hanselman,estimate
from breadloaf_pwm_preview import csv_number
from study_io import write_json


def fields(path):
    return {k:v.strip() for k,v in re.findall(r'^([^=\r\n]+)=(.*)$',Path(path).read_text(encoding='utf-8',errors='replace'),re.M)}


def dimensions(values):
    required=('Slot_Number','Stator_Bore','Slot_Depth','Tooth_Width','Slot_Opening','Tooth_Tip_Depth','Tooth_Tip_Angle','Slot_Corner_Radius','Liner_Thickness')
    d={k:float(values[k]) for k in required}
    if not all(math.isfinite(v) for v in d.values()):raise ValueError('Finite slot dimensions required')
    if values.get('Slot_Type')!='Parallel_Tooth' or d['Slot_Corner_Radius']!=0:raise ValueError('Zero-fillet parallel-tooth template only')
    if d['Slot_Number']<3 or not d['Slot_Number'].is_integer():raise ValueError('Integer slot count required')
    if any(d[k]<=0 for k in required if k not in ('Slot_Corner_Radius','Liner_Thickness')) or d['Liner_Thickness']<0:
        raise ValueError('Positive dimensions and nonnegative liner required')
    if not 0<d['Tooth_Tip_Angle']<90:raise ValueError('Nonzero supported taper angle required')
    beta=math.pi/d['Slot_Number'];R=d['Stator_Bore']/2;opening=d['Slot_Opening']
    if opening>=2*R:raise ValueError('Opening exceeds bore')
    throat=math.sqrt(R*R-(opening/2)**2)+d['Tooth_Tip_Depth']
    slope=2/math.tan(math.radians(d['Tooth_Tip_Angle']))
    denominator=slope-2*math.tan(beta)
    if denominator<=0:raise ValueError('Taper does not intersect supported tooth walls')
    front=(slope*throat-opening-d['Tooth_Width']/math.cos(beta))/denominator
    back=R+d['Slot_Depth']
    if not throat<front<back-d['Liner_Thickness']:raise ValueError('Unsupported slot/taper order')
    d.update(beta=beta,bore_R=R,back_R=back,throat_x=throat,body_front_x=front)
    for liner in (0,d['Liner_Thickness']):
        if wall_halfwidth(d,front,liner)<=0:raise ValueError('Liner closes slot')
    return d


def wall_halfwidth(d,x,liner=0):
    return x*math.tan(d['beta'])-(d['Tooth_Width']/2+liner)/math.cos(d['beta'])


def corner_x(d,liner=0):
    t=math.tan(d['beta']);c=(d['Tooth_Width']/2+liner)/math.cos(d['beta']);R=d['back_R']-liner
    return (t*c+math.sqrt((1+t*t)*R*R-c*c))/(1+t*t)


def body_width(d,x,liner=0):
    x=np.asarray(x,float);R=d['back_R']-liner
    cap=np.sqrt(np.maximum(0,R*R-x*x))
    return np.where((x>=d['body_front_x'])&(x<=R),2*np.minimum(wall_halfwidth(d,x,liner),cap),0.)


def area(d,liner=0):
    front=d['body_front_x'];R=d['back_R']-liner;corner=corner_x(d,liner)
    # Split the line/circular-cap junction for numerical integration.
    return sum(quad(lambda x:float(body_width(d,x,liner)),a,b,epsabs=1e-10,epsrel=1e-11)[0]
               for a,b in ((front,corner),(corner,R)))


def native_width(region,x,beta):
    def rotate(p):return np.array([p['x']*math.cos(beta)+p['y']*math.sin(beta),-p['x']*math.sin(beta)+p['y']*math.cos(beta)])
    hits=[]
    for e in region['entities']:
        a=rotate(e['start']);b=rotate(e['end'])
        if e['type']=='line':
            if abs(b[0]-a[0])<1e-12:continue
            t=(x-a[0])/(b[0]-a[0])
            if -1e-10<=t<=1+1e-10:hits.append(a[1]+t*(b[1]-a[1]))
        elif e['type']=='arc':
            c=rotate(e['centre']);r=abs(e['radius']);disc=r*r-(x-c[0])**2
            if disc<0:continue
            sign=1 if e['radius']>0 else -1
            start=math.atan2(a[1]-c[1],a[0]-c[0]);end=math.atan2(b[1]-c[1],b[0]-c[0]);sweep=sign*(end-start)%(2*math.pi)
            for y in (c[1]-math.sqrt(disc),c[1]+math.sqrt(disc)):
                angle=math.atan2(y-c[1],x-c[0])
                if (sign*(angle-start))%(2*math.pi)<=sweep+1e-10:hits.append(y)
        else:raise ValueError('Unsupported boundary entity')
    unique=[]
    for y in sorted(hits):
        if not unique or abs(y-unique[-1])>1e-8:unique.append(y)
    if len(unique)!=2:raise ValueError('Expected two convex boundary intersections')
    return unique[-1]-unique[0]


def review_geometry(d,regions):
    widths=[]
    for name,liner in [('StatorSlot',0),('Impreg_1',d['Liner_Thickness'])]:
        grid=np.linspace(d['body_front_x']+1e-5,d['back_R']-liner-1e-5,97)
        widths.extend(abs(float(body_width(d,x,liner))-native_width(regions[name],x,d['beta'])) for x in grid)
    wedge=(d['Slot_Opening']+float(body_width(d,d['body_front_x'])))/2*(d['body_front_x']-d['throat_x'])
    half=d['Slot_Opening']/2;R=d['bore_R']
    opening=d['Slot_Opening']*d['throat_x']-(half*math.sqrt(R*R-half*half)+R*R*math.asin(half/R))
    values={'StatorSlot':area(d),'Impreg_1':area(d,d['Liner_Thickness']),'StatorWedge':wedge,'StatorAir':opening}
    return {'maximum_width_difference_mm':max(widths),
            'areas':{k:{'calculated_mm2':v,'saved_native_mm2':regions[k]['area'],'difference_mm2':v-regions[k]['area']} for k,v in values.items()},
            'geometry_qualified_for_template':False}


def detailed_slot(snapshot,d,scenario,quadrature=96):
    from scipy.integrate import cumulative_trapezoid
    if snapshot['slots']!=d['Slot_Number'] or any(not math.isclose(snapshot['geometry_mm'][k],d[k],rel_tol=0,abs_tol=1e-9)
        for k in ('Stator_Bore','Slot_Depth','Tooth_Width','Slot_Opening','Tooth_Tip_Depth')):
        raise ValueError('Snapshot/detail geometry mismatch')
    if isinstance(quadrature,bool) or not isinstance(quadrature,int) or quadrature<4:raise ValueError('Quadrature at least four required')
    sides=[[] for _ in range(snapshot['slots'])]
    for coil in snapshot['coils']:
        vec=np.eye(3)[coil['phase']]*coil['turns']
        sides[coil['start']].append(vec);sides[coil['end']].append(-vec)
    if snapshot['paths']!=1 or any(len(v)!=2 for v in sides):raise ValueError('Two sides/slot, one path required')
    if scenario not in ('mixed','listed_bottom_first','listed_top_first'):raise ValueError('Unknown layer scenario')
    liner=d['Liner_Thickness'];front=d['body_front_x'];back=d['back_R'];conductor_back=back-liner
    # Uniform density by enclosed conductor AREA, not radial height.
    grid=np.linspace(front,conductor_back,8193);width=body_width(d,grid,liner)
    integral=np.r_[0,cumulative_trapezoid(width,grid)];total_area=integral[-1]
    fraction=(total_area-integral)/total_area
    split=float(np.interp(.5,fraction[::-1],grid[::-1]))
    cuts=sorted(set([front,split,corner_x(d),corner_x(d,liner),conductor_back,back]))
    q,w=np.polynomial.legendre.leggauss(quadrature);matrix=np.zeros((3,3));L=snapshot['geometry_mm']['Stator_Lam_Length']/1000
    for slot in sides:
        vectors=np.asarray(slot if scenario!='listed_top_first' else slot[::-1]);turns=vectors.sum(axis=0)
        for low,high in zip(cuts[:-1],cuts[1:]):
            x=low+(q+1)*(high-low)/2;f=np.interp(x,grid,fraction,left=1,right=0)
            enclosed=f[:,None]*turns if scenario=='mixed' else np.clip(f[:,None]*2-np.arange(2),0,1)@vectors
            # dy/b is dimensionless: mm cancel, stack length remains SI.
            matrix+=np.einsum('n,ni,nj->ij',w*(high-low)/(2*body_width(d,x)),enclosed,enclosed)
        throat=d['throat_x'];b0=d['Slot_Opening'];b1=float(body_width(d,front))
        taper=(front-throat)*math.log(b1/b0)/(b1-b0)
        neck=d['Tooth_Tip_Depth']/b0
        matrix+=(taper+neck)*np.outer(turns,turns)
    matrix*=MU0*L
    Q=np.array([[1/math.sqrt(2),1/math.sqrt(6)],[-1/math.sqrt(2),1/math.sqrt(6)],[0,-2/math.sqrt(6)]])
    return {'scenario':scenario,'slot_matrix_H':matrix.tolist(),'slot_balanced_mean_H':float(np.trace(Q.T@matrix@Q)/2),
            'conductor_area_mm2':area(d,liner),'taper_permeance_factor':taper,'neck_permeance_factor':neck,
            'qualified':False,'used_for_guidance':False}


def build(direct,study,persist=True):
    started=time.perf_counter();direct=Path(direct).resolve();study=Path(study).resolve()
    load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    plan=load(direct/'plan.json');mot=Path(plan['source_model']);f=fields(mot)
    if hashlib.sha256(mot.read_bytes()).hexdigest()!=plan['model_sha256']:raise ValueError('Frozen model changed')
    geom=mot.parent/'native_geometry.json';regions=load(geom)['regions'];d=dimensions(f)
    snapshot=load(plan['source_snapshot']);csv=mot.with_suffix('.csv')
    saved=load(study/(plan['candidate_id']+'_snapshot.json'))
    if saved['geometry_mm']!=snapshot['geometry_mm'] or saved['coils']!=snapshot['coils']:
        raise ValueError('Study/source physical snapshot mismatch')
    native_slot,unit,_=csv_number(csv,'Stator Slot Leakage Inductance')
    if unit!='mH':raise ValueError('Slot unit mismatch')
    native_end,unit,_=csv_number(csv,'Armature End Winding Inductance_(Hanselman)')
    if unit!='mH':raise ValueError('End unit mismatch')
    scenarios=[detailed_slot(snapshot,d,s) for s in ('mixed','listed_bottom_first','listed_top_first')]
    for row in scenarios:row['native_slot_relative_difference_pct']=100*(row['slot_balanced_mean_H']/(native_slot*.001)-1)
    old=[estimate(snapshot,float(f['Liner_Thickness']),float(f['Liner_Wire_Gap']),s) for s in ('mixed','listed_bottom_first','listed_top_first')]
    spans={min((c['end']-c['start'])%snapshot['slots'],(c['start']-c['end'])%snapshot['slots']) for c in snapshot['coils']}
    if len(spans)!=1:raise ValueError('Uniform coil span required')
    chord=(d['body_front_x']+d['back_R']-d['Liner_Thickness'])*math.sin(math.pi*next(iter(spans))/snapshot['slots'])/1000
    counts=sum(c['phase']==0 for c in snapshot['coils']);turns=snapshot['turns_per_coil'];a=area(d,d['Liner_Thickness'])
    ends=[]
    for label,coil_area in [('full_conductor_area_per_electrical_layer',a/2),('half_slot_cuboid_area_per_layer_hypothesis',a/4)]:
        value=hanselman(counts,turns,chord,coil_area*1e-6)
        ends.append({'area_policy':label,'coil_area_mm2':coil_area,'mean_coil_chord_mm':chord*1000,'end_H':value,
                     'native_relative_difference_pct':100*(value/(native_end*.001)-1),'qualified':False})
    # Reuse saved earlier geometries to test the geometry reconstruction, not performance.
    holdouts=[];files=[mot,geom,csv,Path(plan['source_snapshot']),study/(plan['candidate_id']+'_snapshot.json')]
    root=direct.parent/'breadloaf_loss_B_validation_20261104'
    for path in sorted(root.glob('*/native_geometry.json')):
        model=path.parent/(path.parent.name+'.mot')
        if not model.is_file():continue
        hd=dimensions(fields(model));check=review_geometry(hd,load(path)['regions'])
        holdouts.append({'case_id':path.parent.name,**check});files.extend([path,model])
    source_positions=[v for k,v in f.items() if 'RadialPosition[' in k and k.startswith('Phase_')]
    result={'schema':'breadloaf-detailed-slot-review-v1','candidate_id':plan['candidate_id'],
            'geometry_check':review_geometry(d,regions),'slot_scenarios':scenarios,'end_area_scenarios':ends,
            'previous_slot_estimates_H':[v['slot_balanced_mean_H'] for v in old],
            'native_slot_H':native_slot*.001,'native_end_H':native_end*.001,
            'saved_geometry_holdouts':holdouts,
            'layer_policy':{'saved_radial_position_codes':sorted(set(source_positions)),
                'physical_layer_mapping_confirmed':False,'thermal_cuboids_are_not_electrical_layers':True,
                'note':'Zero radial-position codes do not establish electrical layer order. Preserve mixed/order/reverse scenarios.'},
            'qualified':False,'family_extension_allowed':False,'new_native_fea':0,'elapsed_s':time.perf_counter()-started,
            'source_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            'limitations':['Exact geometry comparison only within zero-fillet parallel-tooth template; no full magnetics qualification',
                'Uniform area conductor distribution; actual discrete wire packing/layer routing unknown',
                'Wedge and neck magnetic energy are approximations; curved bore opening correction omitted in inductance',
                'End area alternatives remain unresolved; do not select an alternative by closeness to Native',
                'No additional differential leakage, no HF/saturation correction, no automatic ranking or rejection']}
    if persist:write_json(direct/'detailed_slot_review.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);p.add_argument('--study',required=True);a=p.parse_args()
    r=build(a.direct,a.study)
    print(json.dumps({k:v for k,v in r.items() if k not in ('source_files','limitations')},indent=2))
