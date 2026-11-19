"""Prepare one local torque/current correction check; never a new shape holdout."""
import argparse
import hashlib
import json
from pathlib import Path
from review_breadloaf_verification import review
from spm_ripple import predict
from study_io import write_json


def prepare(source, output, max_corrections=1):
    source=Path(source).resolve();output=Path(output).resolve()
    if isinstance(max_corrections,bool) or not isinstance(max_corrections,int) or max_corrections<1:
        raise ValueError('Positive integer correction budget required')
    source_plan=json.loads((source/'plan.json').read_text(encoding='utf-8'))
    generation=source_plan.get('feedback_generation',1 if source_plan.get('schema')=='breadloaf-local-current-feedback-v1' else 0)
    if generation>=max_corrections:
        raise ValueError('Current correction budget exhausted; retain residual, do not launch another FEA')
    if output.exists():raise ValueError('Fresh feedback folder required')
    report=review(source)
    eligible=[r for r in report['cases'] if r['practical_ripple_acceptance']['state']=='passed'
              and r['current_feedback']['status']=='proposed_unverified']
    if not eligible:raise ValueError('No passed ripple case with a current correction inside limits')
    chosen=min(eligible,key=lambda r:r['actual_ripple_pct']);parent=chosen['id']
    s=json.loads((source/(parent+'_snapshot.json')).read_text(encoding='utf-8'))
    original_current=s['line_peak_A'];s['line_peak_A']=chosen['current_feedback']['proposed_line_peak_A']
    s['expected_native']['PeakCurrent']=s['line_peak_A'];s['id']=parent+'_current'+str(generation+1)
    raw=predict(s,5760,960)
    raw['optimization_eligible']=False
    output.mkdir(parents=True);name=s['id']
    write_json(output/(name+'_snapshot.json'),s);write_json(output/(name+'_proxy.json'),raw)
    model=source/parent/(parent+'.mot')
    if not model.is_file() or not (model.parent/'working_materials.mdb').is_file():
        raise ValueError('Previous native model/material database missing')
    case={'id':name,'rotor_id':'surface_breadloaf','source_folder':str(model.parent),
          'source_model_name':model.name,'source_model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
          'snapshot_sha256':hashlib.sha256((output/(name+'_snapshot.json')).read_bytes()).hexdigest(),
          'prediction_sha256':hashlib.sha256((output/(name+'_proxy.json')).read_bytes()).hexdigest(),
          'predicted_ripple_pct':raw['ripple_pct']}
    plan={'schema':'breadloaf-local-current-feedback-v1','cases':[case],'planned_fea':1,'per_case_timeout_s':600,
          'feedback_generation':generation+1,'max_current_corrections':max_corrections,'feedback_source_folder':str(source),
          'scope':'One same-geometry local torque-current correction, NOT new independent shape validation. Flat deferred.',
          'target_electromagnetic_torque_Nm':chosen['current_feedback']['target_torque_Nm'],
          'max_line_peak_A':chosen['current_feedback']['max_line_peak_A'],
          'feedback':{'parent_id':parent,'native_history':chosen['current_feedback_observations'],
                      'native_observation':{'line_peak_A':original_current,
                       'torque_Nm':chosen['current_feedback_observations'][-1]['torque_Nm']},
                      'proposal':chosen['current_feedback'],
                      'raw_model_predicted_torque_Nm':raw['mean_Nm'],
                      'policy':'Only mean native torque informs current proposal. No ripple fit or clipping.'},
          'acceptance':'Assess actual electromagnetic torque and ripple separately. Practical ripple <=50%; actual<=20% reported separately.',
          'production_model_connected':False,'estimated_duration_minutes':[2,4]}
    if source_plan.get('request_contract'):
        plan['request_contract']=source_plan['request_contract']
        plan['target_electromagnetic_torque_Nm']=source_plan['target_electromagnetic_torque_Nm']
        plan['feedback']['torque_metric']=chosen['current_feedback_torque_metric']
    write_json(output/'plan.json',plan)
    return plan


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-corrections',type=int,default=1)
    a=p.parse_args();r=prepare(a.source,a.output,a.max_corrections)
    print(json.dumps({'planned_fea':1,'case':r['cases'][0]['id'],'feedback':r['feedback']},indent=2))
