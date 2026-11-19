"""Offline recovery planning: reject bad boundaries and freeze new predictions."""
import argparse
import hashlib
import json
from pathlib import Path
from magnet_boundary_check import check_region
from spm_ripple import predict,SPM_TYPES
from spm_ripple_calibration import fit,apply
from study_io import write_json


def prepare(first,second,output):
    first=Path(first).resolve();second=Path(second).resolve();output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    training=[];excluded=[];native_ids=set();hashes={}
    for source in (first,second):
        path=source/'result.json' if (source/'result.json').exists() else source/'partial_results.json'
        r=json.loads(path.read_text(encoding='utf-8'));rows=r['runs'] if isinstance(r,dict) else r
        for row in rows:
            native_ids.add(row['id'])
            snapshot=json.loads((source/(row['id']+'_snapshot.json')).read_text(encoding='utf-8'));check=check_region(snapshot['magnet_region'])
            if not check['passed']:excluded.append({'id':row['id'],'source':str(source),'geometry_check':check});continue
            raw=predict(snapshot,2880,480);graph=row['graphs']['TorqueMsVw']
            if len(graph['y'])!=481 or abs(graph['x'][-1]-graph['x'][0]-720)>1e-6:raise ValueError('Unexpected cycle convention')
            training.append({'id':row['id'],'rotor_id':row['rotor_id'],'proxy':raw,'actual_waveform_Nm':graph['y'][:-1]})
            f=source/(row['id']+'_validation.json');hashes[str(f)]=hashlib.sha256(f.read_bytes()).hexdigest()
    calibration=fit(training);write_json(output/'calibration.json',calibration)
    write_json(output/'excluded_training.json',excluded)
    pool=[];rejected=[]
    for f in sorted(second.glob('*_snapshot.json')):
        snapshot=json.loads(f.read_text(encoding='utf-8'));check=check_region(snapshot['magnet_region'])
        if not check['passed']:rejected.append({'id':snapshot['id'],'geometry_check':check});continue
        if snapshot['id'] in native_ids:continue
        # Deliberate holdout experiment, never a production prediction.
        proxy=apply(predict(snapshot,2880,480),calibration,allow_unseen_shape=True)
        name=snapshot['id'];write_json(output/(name+'_proxy.json'),proxy)
        write_json(output/(name+'_snapshot.json'),snapshot)
        pool.append({'id':name,'rotor_id':snapshot['rotor_id'],'source_folder':str(second),
            'predicted_ripple_pct':proxy['ripple_pct'],'geometry_check':check,
            'source_model_sha256':hashlib.sha256((second/(name+'.mot')).read_bytes()).hexdigest(),
            'snapshot_sha256':hashlib.sha256((output/(name+'_snapshot.json')).read_bytes()).hexdigest(),
            'prediction_sha256':hashlib.sha256((output/(name+'_proxy.json')).read_bytes()).hexdigest()})
    selected=[]
    for rotor in ('surface_flat','surface_breadloaf'):
        valid=[x for x in pool if x['rotor_id']==rotor and x['predicted_ripple_pct'] is not None]
        selected+=sorted(valid,key=lambda x:x['predicted_ripple_pct'])[:2]
    write_json(output/'rejected_candidates.json',rejected)
    plan={'schema':'spm-ripple-recovery-v1','cases':selected,'planned_fea':len(selected),
        'required_types':list(SPM_TYPES),'training_ids':[r['id'] for r in training],
        'active_types':['surface_flat','surface_breadloaf'],
        'deferred_types':['surface_radial','surface_parallel'],
        'deferred_reason':'Existing cases retained; recalibrated model still requires later independent checks. No production qualification.',
        'all_prior_native_ids_excluded':sorted(native_ids),'training_source_sha256':hashes,
        'per_case_timeout_s':600,'acceptance':'predicted<=20%, native<=50%',
        'production_model_connected':False,'independence':'All selected cases exclude every earlier native FEA case ID.',
        'limitations':['Flat/Breadloaf transfer calibration has no training data; independent checks required.',
            'Simple boundary checks do not certify mesh validity, saturation or manufacturing.',
            'Previous invalid-boundary FEA may have repaired geometry; not used as paired calibration.']}
    write_json(output/'plan.json',plan)
    return plan


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--first',type=Path,required=True);p.add_argument('--second',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=prepare(a.first,a.second,a.output)
    print(json.dumps({'training_count':len(r['training_ids']),'planned_fea':r['planned_fea'],'selected':[(c['id'],c['predicted_ripple_pct']) for c in r['cases']]}))
