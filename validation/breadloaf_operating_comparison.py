"""Compare saved search predictions with independent FEA; never refit or run FEA."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from study_io import write_json


def compare(study,batch):
    study=Path(study).resolve();batch=Path(batch).resolve()
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    search=load(study/'result.json');native=load(batch/'result.json');plan=load(batch/'plan.json')
    candidates={f['id']:f for f in search['finalists']}
    cases={c['id']:c for c in plan['cases']};rows=[]
    for outcome in native['outcomes']:
        if outcome['status']!='completed':continue
        name=outcome['id']
        if name not in candidates:raise ValueError('Native case missing from saved search')
        prediction_path=study/(name+'_high_resolution.json')
        saved=load(prediction_path);matched=saved['matched']
        snapshot_path=batch/(name+'_snapshot.json');snapshot=load(snapshot_path)
        source=load(study/(name+'_snapshot.json'))
        for suffix,key in (('_snapshot.json','snapshot_sha256'),('_proxy.json','prediction_sha256')):
            if hashlib.sha256((batch/(name+suffix)).read_bytes()).hexdigest()!=cases[name][key]:
                raise ValueError('Frozen batch evidence changed')
        for key,value in source['expected_native'].items():
            if key!='PeakCurrent' and snapshot['expected_native'].get(key)!=value:
                raise ValueError('Prediction and Native input mismatch: '+key)
        if not math.isclose(matched['line_peak_A'],snapshot['line_peak_A'],abs_tol=1e-8,rel_tol=0):
            raise ValueError('Prediction and Native current mismatch')
        local=matched.get('model_screens',{}).get('local_calibrated_estimate',{})
        v=outcome['values']
        predictions={'ripple_pct':matched['ripple_pct'],
                     'shaft_torque_Nm':matched.get('predicted_shaft_torque_Nm'),
                     'efficiency_pct':local.get('efficiency_pct'),
                     'electromagnetic_torque_Nm':local.get('values',{}).get('Average torque (MsVw)')}
        actual={'ripple_pct':outcome['actual_ripple_pct'],'shaft_torque_Nm':v.get('Shaft Torque'),
                'efficiency_pct':v.get('System Efficiency'),'electromagnetic_torque_Nm':v.get('Average torque (MsVw)')}
        metrics={k:{'predicted':p,'actual':actual[k],
                    'prediction_minus_actual':p-actual[k] if p is not None and actual[k] is not None else None}
                 for k,p in predictions.items()}
        rows.append({'id':name,'metrics':metrics,'line_peak_A':snapshot['line_peak_A'],
                     'prediction_sha256':hashlib.sha256(prediction_path.read_bytes()).hexdigest()})
    report={'schema':'breadloaf-operating-comparison-v1','cases':rows,
            'source_study':str(study),'source_batch':str(batch),
            'native_result_sha256':hashlib.sha256((batch/'result.json').read_bytes()).hexdigest(),
            'refit_performed':False,'new_native_fea':0,'family_qualified':False,
            'scope':'Retrospective linkage of saved predictions to independent FEA at identical inputs. Not new holdout qualification.'}
    write_json(batch/'operating_comparison.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--batch',required=True)
    a=p.parse_args();print(json.dumps(compare(a.study,a.batch),indent=2))
