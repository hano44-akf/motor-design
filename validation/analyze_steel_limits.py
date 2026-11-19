"""Read-only B-H consistency/operating-density analysis of archived material data.
No material values or program limits are changed. No extrapolation is used.
"""
from pathlib import Path
from collections import defaultdict
import json
import math
import statistics

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'material_library/20261019_161745/materials_raw.json'
OUT=ROOT/'outputs/steel_limits_20261022'
MU0=4*math.pi*1e-7

def interpolate(pairs,x):
    points=sorted(set(pairs))
    for xx,yy in points:
        if x==xx:return yy
    for (xa,ya),(xb,yb) in zip(points,points[1:]):
        if xa<x<xb:return ya+(yb-ya)*(x-xa)/(xb-xa)
    return None

def analyze(material):
    fields={e['key']:e['value'] for e in material['raw_entries']}
    arrays=material.get('indexed_arrays',{})
    h={x['index']:float(x['raw_value']) for x in arrays.get('HValue',[])}
    b={x['index']:float(x['raw_value']) for x in arrays.get('BValue',[])}
    points=[(h[i],b[i]) for i in sorted(h.keys()&b.keys())]
    finite=all(math.isfinite(hh) and math.isfinite(bb) for hh,bb in points)
    increasing=finite and len(points)>1 and all(hb>ha and bb>ba for (ha,ba),(hb,bb) in zip(points,points[1:]))
    sampled={}
    for target in [1.4,1.5,1.6,1.7,1.8,1.9,2.0,2.076]:
        value=interpolate([(bb,hh) for hh,bb in points],target) if increasing else None
        below=interpolate([(bb,hh) for hh,bb in points],target-.01) if increasing else None
        above=interpolate([(bb,hh) for hh,bb in points],target+.01) if increasing else None
        sampled[str(target)]={'H_A_m':value,'incremental_relative_permeability_0p02T_window':.02/(MU0*(above-below)) if above is not None and below is not None and above>below else None}
    try:thickness=float(fields.get('LaminationThickness','nan'))
    except ValueError:thickness=None
    freq=sorted({float(e['raw_value']) for e in arrays.get('Frequency',[])})
    bs=[float(e['raw_value']) for e in arrays.get('FluxDensity',[])]
    return {'name':material['name'],'id':material['id'],'point_count':len(points),
            'monotone_original_order':increasing,'thickness_mm':thickness,
            'BH_range_H_A_m':[points[0][0],points[-1][0]] if points else None,
            'BH_range_B_T':[points[0][1],points[-1][1]] if points else None,
            'B_at_2500_A_m_T':interpolate(points,2500) if increasing else None,
            'B_at_5000_A_m_T':interpolate(points,5000) if increasing else None,
            'B_at_10000_A_m_T':interpolate(points,10000) if increasing else None,
            'operating_density_samples':sampled,
            'loss_table_frequencies_Hz':freq,'loss_table_B_range_T':[min(bs),max(bs)] if bs else None,
            'notes':fields.get('Notes',''),'origins':material.get('origins',[]),
            'extrapolation_metadata':{k:v for k,v in fields.items() if any(t in k.lower() for t in ['extrap','limit','knee'])}}

def main():
    data=json.loads(SOURCE.read_text(encoding='utf-8'))
    recent={g['export_sha256'] for g in data['granta_provenance'] if '20261019_131932' in g['report_path']}
    groups=defaultdict(list)
    for material in data['materials']:
        if material['name'].startswith('POSCO |') or 's45c' in material['name'].lower():groups[material['name']].append(material)
    all_versions=[];selected=[]
    for name,versions in sorted(groups.items()):
        winner=sorted(versions,key=lambda m:(any(o['database_sha256'] in recent for o in m['origins']),m['id']),reverse=True)[0]
        rows=[analyze(m) for m in versions];all_versions.extend(rows)
        selected.append(next(row for row in rows if row['id']==winner['id']))
    normal=[r for r in selected if r['name'].startswith('POSCO |') and r['name']!='POSCO | 35PN230' and r['monotone_original_order']]
    ranges={}
    for key in ['1.6','1.7','1.8','1.9','2.0']:
        values=[r['operating_density_samples'][key]['H_A_m'] for r in normal]
        values=[v for v in values if v is not None]
        ranges[key]={'minimum_H_A_m':min(values),'median_H_A_m':statistics.median(values),'maximum_H_A_m':max(values),'count':len(values)} if values else None
    result={'source':str(SOURCE.relative_to(ROOT)),'method':'Indexed B/H points, strict monotonicity screen, piecewise linear interpolation within stored range only. Differential permeability is a 0.02T secant window, not a measured HF value. Prefer latest API export, preserve all versions. 35PN230 excluded from aggregate due to prior consistency flag. No universal knee/saturation criterion invented.',
            'selected_records':selected,'all_versions':all_versions,'normal_POSCO_summary':ranges}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'steel_BH_analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    for row in selected:
        print(json.dumps({k:row[k] for k in ['name','point_count','B_at_5000_A_m_T','operating_density_samples','extrapolation_metadata']},ensure_ascii=True))

if __name__=='__main__':main()
