"""Read native .txt winding exports; verify phasors without launching a solver."""
import cmath
import itertools
import json
import math
from pathlib import Path
import re
from winding_layout import synthesize


def review(path):
    text=Path(path).read_text(encoding='utf-8',errors='replace')
    fields=dict(re.findall(r'^([^=\r\n]+)=(.*)$',text,re.M))
    fields={k:v.strip() for k,v in fields.items()}
    q=int(fields['Slot_Number']);p=int(fields['Pole_Number']);phases=int(fields['MagPhases'])
    if phases!=3:raise ValueError('This review supports three phases only')
    coils=[]
    for key,value in fields.items():
        m=re.fullmatch(r'Phase_(\d+)Path_(\d+)_GoSlot\[(\d+)\]',key)
        if not m:continue
        phase,path_id,index=map(int,m.groups());prefix=f'Phase_{phase}Path_{path_id}_'
        start=int(value);end=int(fields[prefix+f'ReturnSlot[{index}]']);turns=int(fields[prefix+f'Turns[{index}]'])
        if not (0<=start<q and 0<=end<q and turns>0):raise ValueError('Invalid native coil')
        coils.append({'phase':phase-1,'path':path_id,'start':start,'end':end,'turns':turns})
    if not coils:raise ValueError('No winding coils found')
    paths={c['path'] for c in coils}
    if len(paths)!=1:raise ValueError('Parallel paths require path-by-path review')
    theta=math.pi*p/q
    harmonics={};phasors=[]
    for h in (1,3,5,7,9,11,13):
        sums=[sum(c['turns']*(cmath.exp(1j*h*theta*c['start'])-cmath.exp(1j*h*theta*c['end'])) for c in coils if c['phase']==phase) for phase in range(3)]
        denominators=[2*sum(c['turns'] for c in coils if c['phase']==phase) for phase in range(3)]
        if not all(denominators):raise ValueError('Missing phase')
        harmonics[str(h)]=[abs(v)/n for v,n in zip(sums,denominators)]
        if h==1:phasors=sums
    factors=harmonics['1'];angles=[math.degrees(cmath.phase(v)) for v in phasors]
    phase_steps=[(angles[i]-angles[0])%360 for i in (1,2)]
    balanced=max(factors)-min(factors)<1e-9 and sorted(round(v,7) for v in phase_steps)==[120.,240.]
    spans=sorted({min((c['end']-c['start'])%q,(c['start']-c['end'])%q) for c in coils})
    synthesized=synthesize(p,q,spans[0] if len(spans)==1 else None)
    generated=[(ord(c['phase'])-65,(c['start_slot']-1 if c['sign']==1 else c['end_slot']-1),
                (c['end_slot']-1 if c['sign']==1 else c['start_slot']-1)) for c in synthesized['coils']]
    target=sorted((c['phase'],c['start'],c['end']) for c in coils)
    match=None
    if len({c['turns'] for c in coils})==1:
        for permutation in itertools.permutations(range(3)):
            for shift in range(q):
                for reverse in (False,True):
                    mapped=sorted((permutation[phase],((end if reverse else start)+shift)%q,((start if reverse else end)+shift)%q) for phase,start,end in generated)
                    if mapped==target:match={'phase_permutation':list(permutation),'slot_offset':shift,'global_reverse':reverse};break
                if match:break
            if match:break
    counts=[sum(c['phase']==phase for c in coils) for phase in range(3)]
    occupancy=[sum(c['start']==s or c['end']==s for c in coils) for s in range(q)]
    return {'source':str(path),'poles':p,'slots':q,'native_layers':int(fields['WindingLayers']),
        'coils_per_phase':counts,'coil_span_slots':spans,'slot_coil_side_counts':occupancy,
        'phase_angles_ed':angles,'relative_phase_angles_ed':phase_steps,
        'fundamental_winding_factors':factors,'harmonic_winding_factors':harmonics,
        'balanced':balanced,'synthesized_layout_equivalence':match,
        'coils':coils,'scope':'Slot/turn phasor and topology comparison only. Phase permutation/offset is a convention conversion, not permission to change native current ordering. Layer insulation, physical routing and manufacturability remain separate.'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();r=review(args.source);args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:r[k] for k in ('balanced','fundamental_winding_factors','relative_phase_angles_ed','synthesized_layout_equivalence')}))
