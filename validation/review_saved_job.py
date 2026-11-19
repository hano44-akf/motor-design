"""Re-evaluate saved electromagnetic evidence against new controller requirements.

No Motor-CAD calculation is performed. Source run files remain unchanged.
"""
import argparse
import copy
import json
import time
from pathlib import Path
from design_job import validate,assess_run,export_job,write_json
from controller_limits import pole_limit,torque_ripple_limit,current_ripple_limit

def review(source,output,ripple=20,frequency=10000):
    began=time.perf_counter()
    data=copy.deepcopy(json.loads((source/'result.json').read_text(encoding='utf-8')))
    request=data['request'];request['switching_frequency_hz']=frequency
    request['pwm_current_ripple_max_pct']=current_ripple_limit(request.get('pwm_current_ripple_max_pct'))
    request['operating_point']['torque_ripple_max_pct']=ripple;validate(request)
    for candidate in data['results']:
        for run in candidate['runs']:
            run['assessment']=assess_run(run,request)
            run['source_run_file']=str((source/(run['label']+'.json')).resolve())
        candidate['physical_screens_pass']=all(r['assessment']['physical_screens_pass'] for r in candidate['runs'])
        candidate['target_met']=all(r['assessment']['target_met'] for r in candidate['runs'])
        candidate['known_targets_met']=all(r['assessment']['known_targets_met'] for r in candidate['runs'])
        candidate['requirements_fully_verified']=all(r['assessment']['requirements_fully_verified'] for r in candidate['runs'])
        references={**request['operating_point'],'efficiency_pct':request['operating_point'].get('efficiency_min_pct') or 100}
        candidate['worst_normalized_shortfall']=max(sum(d/max(abs(references.get(k) or 1),1e-9) if d is not None else 1e6 for k,d in r['assessment']['shortfalls'].items()) for r in candidate['runs'])
    data['results'].sort(key=lambda c:(not c['physical_screens_pass'],not c['target_met'],c['worst_normalized_shortfall'],-c['worst_efficiency_pct']))
    valid=[c for c in data['results'] if c['physical_screens_pass']]
    data.update(status='target_met' if any(c['target_met'] for c in valid) else 'verification_incomplete' if any(c['known_targets_met'] for c in valid) else 'best_effort' if valid else 'no_screened_candidate',
                best_available=valid[0]['id'] if valid else None,
                effective_torque_ripple_limit_pct=torque_ripple_limit(ripple),
                effective_pwm_current_ripple_max_pct=current_ripple_limit(request.get('pwm_current_ripple_max_pct')),
                controller_configuration=pole_limit(request['operating_point']['speed_rpm'],frequency,4),
                review_only=True,source_job=str(source.resolve()),new_magnetic_solves=0)
    data['timings']['source_session_wall_s']=data['timings']['session_wall_s']
    data['timings']['session_wall_s']=time.perf_counter()-began
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/'request.json',request);write_json(output/'result.json',data)
    export_job(output,data);write_json(output/'progress.json',{'status':'completed','review_only':True,'result_status':data['status']})
    return data

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('source',type=Path);parser.add_argument('--output',type=Path);args=parser.parse_args()
    output=args.output or Path(__file__).resolve().parent/'jobs'/time.strftime('%Y%m%d_%H%M%S')
    result=review(args.source,output)
    print(json.dumps({'output':str(output),'status':result['status'],'new_solves':0,'target_met_models':sum(c['target_met'] for c in result['results'])}))
