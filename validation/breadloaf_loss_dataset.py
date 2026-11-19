"""Paired loss/B development records, with frozen holdouts kept separate."""
import argparse
import hashlib
import json
from pathlib import Path
from spm_ripple import predict
from breadloaf_screens import evaluate,reference
from study_io import write_json

ROOT=Path(__file__).resolve().parent.parent


def build(batch):
    batch=Path(batch).resolve();plan=json.loads((batch/'plan.json').read_text(encoding='utf-8'));rows=[]
    ref=reference()
    folders=[(ROOT/'outputs'/name,None) for name in ('spm_ripple_recovery_20261103','breadloaf_shape_verification_20261104','breadloaf_current_feedback_20261104')]
    folders.append((batch,{c['id']:c['role'] for c in plan['cases']}))
    completed_new=0;failed_new=0
    for folder,roles in folders:
        path=folder/'result.json' if (folder/'result.json').is_file() else folder/'partial_results.json'
        if not path.is_file():continue
        content=json.loads(path.read_text(encoding='utf-8'));outcomes=content.get('outcomes',[]) if isinstance(content,dict) else content
        for row in outcomes:
            if row.get('rotor_id')!='surface_breadloaf':continue
            if row['status']!='completed':
                if roles is not None:failed_new+=1
                continue
            if roles is not None:completed_new+=1
            name=row['id'];snapshot_path=folder/(name+'_snapshot.json');s=json.loads(snapshot_path.read_text(encoding='utf-8'))
            raw=predict(s,2880,480);screen=evaluate(raw,s,s['line_peak_A'],ref);v=row['values']
            role=roles[name] if roles is not None else 'existing_development'
            rows.append({'id':name,'role':role,'training_allowed':role in ('development','existing_development'),
                'source':str(folder),'snapshot_sha256':hashlib.sha256(snapshot_path.read_bytes()).hexdigest(),
                'native_result_sha256':hashlib.sha256((folder/name/'result.json').read_bytes()).hexdigest() if (folder/name/'result.json').exists() else hashlib.sha256(path.read_bytes()).hexdigest(),
                'features':{k:s['expected_native'][k] for k in ('Slot_Opening','Magnet_Arc_[ED]','MagnetReduction','PeakCurrent','ShaftSpeed')},
                'raw_tooth_section_B_T':screen['tooth_section_average_max_B_T'],'raw_yoke_section_B_T':screen['yoke_section_average_max_B_T'],
                'raw_mean_electromagnetic_torque_Nm':raw['mean_Nm'],
                'native':{k:v.get(k) for k in ('Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)',
                    'Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)',
                    'Stator iron Loss [total] (on load)','Rotor iron Loss [total] (on load)','Magnet Loss (on load)',
                    'Average torque (MsVw)','Shaft Torque','System Efficiency')},'qualified':False})
    counts={'existing_reused':sum(r['role']=='existing_development' for r in rows),
            'new_required_first_batch':len(plan['cases']),'new_completed':completed_new,'new_failed':failed_new,
            'new_not_finished':len(plan['cases'])-completed_new-failed_new,
            'remaining_required_first_batch':len(plan['cases'])-completed_new,
            'scope':'Remaining count includes unsuccessful cases. Future model qualification may require more FEA.'}
    result={'schema':'breadloaf-loss-B-paired-data-v1','rows':rows,'counts':counts,
            'training_ids':[r['id'] for r in rows if r['training_allowed']],
            'excluded_from_training_ids':[r['id'] for r in rows if not r['training_allowed']],
            'qualified':False,'new_fea_started_by_this_script':0}
    write_json(batch/'paired_dataset.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--batch',type=Path,required=True);a=p.parse_args()
    print(json.dumps(build(a.batch)['counts'],indent=2))
