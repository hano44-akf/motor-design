"""Freeze raw, current-matched predictions for new Breadloaf FEA holdouts."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import numpy as np
from spm_ripple import ripple
from study_io import write_json


def prepare(study, model, output, selected_ids=None):
    study=Path(study).resolve();model=Path(model).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Fresh verification folder required')
    if not model.is_file() or not (model.parent/'working_materials.mdb').is_file():
        raise ValueError('Native seed model and material database required')
    report=json.loads((study/'result.json').read_text(encoding='utf-8'))
    finalists=report['finalists']
    if selected_ids is not None:
        if not isinstance(selected_ids,list) or not selected_ids or any(not isinstance(x,str) for x in selected_ids) or len(set(selected_ids))!=len(selected_ids) or not set(selected_ids)<={r['id'] for r in finalists}:
            raise ValueError('Distinct saved finalist IDs required')
        finalists=[r for r in finalists if r['id'] in selected_ids]
    output.mkdir(parents=True);cases=[]
    for finalist in finalists:
        name=finalist['id'];s=json.loads((study/(name+'_snapshot.json')).read_text(encoding='utf-8'))
        if s['rotor_id']!='surface_breadloaf':raise ValueError('Breadloaf only; Flat remains deferred')
        data=json.loads((study/(name+'_high_resolution.json')).read_text(encoding='utf-8'))
        matched=data['matched']
        if matched['status'] not in ('matched_in_linear_model','target_not_reached_within_current_limit',
                'matched_shaft_in_local_model','shaft_target_not_reached_within_domain','shaft_matching_unverified'):continue
        raw=copy.deepcopy(data['raw_proxy']);scale=matched['current_scale']
        raw['mutual_Nm']=(np.array(raw['mutual_Nm'])*scale).tolist()
        raw['reluctance_Nm']=(np.array(raw['reluctance_Nm'])*scale**2).tolist()
        if raw.get('electromagnetic_state'):
            raw['electromagnetic_state']['reference_phase_current_A']=(np.array(raw['electromagnetic_state']['reference_phase_current_A'])*scale).tolist()
        wave=np.array(raw['cogging_Nm'])+np.array(raw['mutual_Nm'])+np.array(raw['reluctance_Nm'])
        raw.update(**ripple(wave),torque_Nm=wave.tolist(),qualified=False,optimization_eligible=False)
        raw['acceptance']={'state':'unverified','reason':'Frozen raw prediction; independent FEA pending'}
        s['reference_line_peak_A_before_matching']=s['line_peak_A']
        s['line_peak_A']=matched['line_peak_A'];s['expected_native']['PeakCurrent']=matched['line_peak_A']
        write_json(output/(name+'_snapshot.json'),s);write_json(output/(name+'_proxy.json'),raw)
        cases.append({'id':name,'rotor_id':s['rotor_id'],'source_folder':str(model.parent),
                      'source_model_name':model.name,'source_model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
                      'snapshot_sha256':hashlib.sha256((output/(name+'_snapshot.json')).read_bytes()).hexdigest(),
                      'prediction_sha256':hashlib.sha256((output/(name+'_proxy.json')).read_bytes()).hexdigest(),
                      'predicted_ripple_pct':raw['ripple_pct']})
    plan={'schema':'breadloaf-current-matched-verification-v1','cases':cases,'planned_fea':len(cases),
          'source_search':str(study),
          'source_search_result_sha256':hashlib.sha256((study/'result.json').read_bytes()).hexdigest(),
          'per_case_timeout_s':600,'production_model_connected':False,
          'selection':'Saved selected finalists, frozen before FEA; may be current-limited best effort, never assumed target-met.',
          'source_selection_status':report.get('selection_status','historical_current_matched_candidates'),
          'scope':'New Breadloaf-only analytic geometry and current-matched holdouts. Flat deferred. No refit.',
          'target_electromagnetic_torque_Nm':report['plan']['target_electromagnetic_torque_Nm'],
          'max_line_peak_A':report['plan']['max_line_peak_A'],
          'variables':report['plan']['variables'],'free_variable_count':report['plan'].get('free_variable_count'),
          'grid_combinations_before_geometry_screen':report['plan']['grid_combinations_before_geometry_screen'],
          'geometry_readback_required':True,'acceptance':'predicted<=20%, native<=50%; not actual<=20% certification',
          'estimated_duration_minutes':[2*len(cases),4*len(cases)],
          'maximum_timeout_budget_minutes':len(cases)*10,
          'limitations':['Native torque must be checked independently; local calibrated shaft matching remains an unverified estimate.',
                         'Low-voltage feasibility, efficiency, flux density and other targets are not certified by ripple acceptance.']}
    if report['plan'].get('request_contract'):plan['request_contract']=report['plan']['request_contract']
    write_json(output/'plan.json',plan)
    return plan


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();r=prepare(a.study,a.model,a.output)
    print(json.dumps({'planned_fea':r['planned_fea'],'predictions':[c['predicted_ripple_pct'] for c in r['cases']]}))
