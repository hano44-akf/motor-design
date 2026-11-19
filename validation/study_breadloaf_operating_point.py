"""Offline current-matched Breadloaf study using saved, geometry-valid profiles."""
import argparse
import json
import time
from pathlib import Path

from magnet_boundary_check import check_region
from spm_ripple import ripple
from spm_ripple_operating_point import at_current, match_torque
from study_io import write_json


def run(source, output, target=.5, max_current=40):
    start=time.perf_counter();source=Path(source).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Fresh output folder required')
    output.mkdir(parents=True)
    prior=json.loads((source/'result.json').read_text(encoding='utf-8'))
    native={r['id']:r for r in prior['outcomes'] if r['status']=='completed'}
    rows=[]
    for file in sorted(source.glob('surface_breadloaf_*_snapshot.json')):
        s=json.loads(file.read_text(encoding='utf-8'))
        if not check_region(s['magnet_region'])['passed']:continue
        saved=json.loads((source/(s['id']+'_proxy.json')).read_text(encoding='utf-8'))
        # Stored component arrays are the original raw C/M/R, not the corrected
        # total waveform. Preserve the source, build a separate raw record.
        raw={**saved,'calibration':'none'}
        reference=at_current(raw,s['line_peak_A'],s['line_peak_A'])
        matched=match_torque(raw,s['line_peak_A'],target,max_current)
        row={'id':s['id'],'reference_line_peak_A':s['line_peak_A'],
             'raw_reference_ripple_pct':reference['ripple_pct'],
             'raw_reference_mean_Nm':reference['mean_Nm'],
             'matched':{k:v for k,v in matched.items() if k!='torque_Nm'},
             'independent_native_at_matched_current':False,'qualified':False}
        if s['id'] in native:
            row['existing_native_reference_ripple_pct']=native[s['id']]['actual_ripple_pct']
            row['existing_native_reference_mean_Nm']=native[s['id']]['values']['Average torque (MsVw)']
        if 'torque_Nm' in matched:write_json(output/(s['id']+'_matched_waveform.json'),matched)
        rows.append(row)
    feasible=[r for r in rows if r['matched']['status']=='matched_in_linear_model']
    ranked=sorted(feasible,key=lambda r:r['matched']['ripple_pct'])
    report={'schema':'breadloaf-current-matching-study-v1','source':str(source),
            'target_electromagnetic_torque_Nm':target,'max_line_peak_A':max_current,
            'geometry_candidates':len(rows),'current_angle_sweep_count':0,'new_fea_count':0,
            'elapsed_s':time.perf_counter()-start,'rows':rows,
            'ranked_ids':[r['id'] for r in ranked],
            'predicted_le20_count':sum(r['matched']['ripple_pct']<=20 for r in feasible),
            'production_optimizer_connected':False,'qualified':False,
            'limitations':['Development torque target only, not a new user specification or shaft torque claim.',
                           'Fixed geometry pool, not a completed geometry optimization.',
                           'Linear, Id=0 model. No saturation, voltage or actual-current FEA validation.',
                           'Existing FEA is at reference current only; matched-current predictions are unverified.',
                           'Flat ripple is deferred by user; no Flat work performed.']}
    write_json(output/'result.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--target-electromagnetic-torque',type=float,default=.5);p.add_argument('--max-line-peak-current',type=float,default=40)
    a=p.parse_args();r=run(a.source,a.output,a.target_electromagnetic_torque,a.max_line_peak_current)
    print(json.dumps(r,indent=2))
