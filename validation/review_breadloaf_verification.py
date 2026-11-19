"""Offline assessment: keep ripple evidence separate from torque completion."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from result_policy import requirement, summarize_requirements
from spm_ripple import acceptance
from native_torque_feedback import propose_current
from study_io import write_json


def review(folder):
    folder=Path(folder).resolve()
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    cases={c['id']:c for c in plan['cases']};rows=[]
    target=plan['target_electromagnetic_torque_Nm']
    for row in result['outcomes']:
        if row['status']!='completed':continue
        name=row['id'];case=cases[name];v=row['values']
        for suffix,key in (('_snapshot.json','snapshot_sha256'),('_proxy.json','prediction_sha256')):
            if hashlib.sha256((folder/(name+suffix)).read_bytes()).hexdigest()!=case[key]:
                raise ValueError('Frozen evidence changed: '+name)
        snapshot=json.loads((folder/(name+'_snapshot.json')).read_text(encoding='utf-8'))
        current=snapshot['line_peak_A'];torque=v.get('Average torque (MsVw)')
        constraints={'electromagnetic_torque':requirement(torque,target),
                     'actual_ripple_20pct':requirement(row['actual_ripple_pct'],20,'max')}
        contract=plan.get('request_contract')
        metric='Average torque (MsVw)'
        feedback_target=target
        if contract:
            limits=contract['requirements'];metric='Shaft Torque';feedback_target=contract['requested_shaft_torque_Nm']
            constraints.update(shaft_torque=requirement(v.get(metric),feedback_target),
                efficiency=requirement(v.get('System Efficiency'),limits['efficiency_min_pct']),
                dc_current=requirement(v.get('DC Supply Current (mean)'),limits['dc_current_max_A'],'max'),
                requested_ripple=requirement(row['actual_ripple_pct'],limits['torque_ripple_max_pct'],'max'),
                pwm_current_ripple=requirement(None,contract['pwm_current_ripple_max_pct'],'max'))
            phase=v.get('Phase Current (rms)');area=math.pi*1.8**2/4
            constraints['current_density']=requirement(phase/area if isinstance(phase,(int,float)) else None,limits['current_density_max_A_mm2'],'max')
            for field in ('Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)','Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)'):
                constraints[field]=requirement(v.get(field),limits['flux_density_max_T'],'max')
            constraints['native_voltage_limit']=requirement(0 if row.get('voltage_limit_exceeded') is False else 1 if row.get('voltage_limit_exceeded') is True else None,0,'max')
            if len(contract['voltages_V'])>1:constraints['additional_voltages']=requirement(None,1)
        prior=plan.get('feedback',{})
        observations=list(prior.get('native_history',[prior['native_observation']] if prior.get('native_observation') else []))
        observations.append({'line_peak_A':current,'torque_Nm':v.get(metric)})
        feedback=propose_current(observations,feedback_target,plan.get('max_line_peak_A',40))
        torque_requirement=constraints.get('shaft_torque',constraints['electromagnetic_torque'])
        if torque_requirement['state']=='passed':
            feedback={'status':'not_needed_target_met','target_torque_Nm':feedback_target,
                      'native_verification_required':False,'qualified':False,
                      'reason':'Native torque already meets the minimum target; preserve the verified current.'}
        fields=['Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)',
                'Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)']
        rows.append({'id':name,'predicted_ripple_pct':case['predicted_ripple_pct'],
                     'actual_ripple_pct':row['actual_ripple_pct'],
                     'practical_ripple_acceptance':acceptance(case['predicted_ripple_pct'],row['actual_ripple_pct']),
                     'mean_electromagnetic_torque_Nm':torque,'shaft_torque_Nm':v.get('Shaft Torque'),
                     'electromagnetic_torque_error_pct':100*(torque-target)/target,
                     'line_peak_A':current,'efficiency_pct':v.get('System Efficiency'),
                     'native_voltage_limit_exceeded':row.get('voltage_limit_exceeded'),
                     'flux_density_outputs_T':{k:v.get(k) for k in fields},
                     'requirements':constraints,'requirement_summary':summarize_requirements(constraints),
                     'current_feedback':feedback,'current_feedback_torque_metric':metric,'current_feedback_observations':observations,'solver_s':row.get('solver_s'),
                     'family_qualified':False})
    report={'schema':'breadloaf-verification-review-v1','source':str(folder),'elapsed_s':result['elapsed_s'],
            'cases':rows,'ripple_passed_cases':sum(r['practical_ripple_acceptance']['state']=='passed' for r in rows),
            'actual_ripple_le20_cases':sum(r['actual_ripple_pct']<=20 for r in rows),
            'torque_target_passed_cases':sum(r['requirements']['electromagnetic_torque']['state']=='passed' for r in rows),
            'production_optimizer_connected':False,
            'scope':'Selected nearby Breadloaf candidates at fixed development point, not family-wide qualification. Current correction needs new FEA.'}
    write_json(folder/'verification_review.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True)
    a=p.parse_args();r=review(a.folder)
    print(json.dumps({k:r[k] for k in ('ripple_passed_cases','actual_ripple_le20_cases','torque_target_passed_cases')},indent=2))
