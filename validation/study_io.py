"""Shared persisted JSON/CSV formats; no native solver dependency."""
import json
import csv
from export_csv import clean,cell,flatten
from controller_limits import pole_limit,current_ripple_limit,torque_ripple_limit
from flux_limits import flux_density_limit
from csv_metadata import metadata,evidence_for

def write_json(path,data):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(clean(data),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)

def export_job(folder,result):
    header=['model','source','field','value','status','unit','basis','condition_id','evidence']
    groups={'inputs':[['','request',k,v,'requested'] for k,v in flatten(result['request'])],
            'results':[[c['id'],'selection',k,v,result['status']] for c in result['results'] for k,v in flatten({k:v for k,v in c.items() if k!='runs'})],
            'motorcad':[[c['id'],r['label'],k,v,'saved_MotorCAD_output'] for c in result['results'] for r in c['runs'] for k,v in flatten(r)]}
    groups['results'] += [['','job_metadata',k,v,result['status']] for k,v in flatten({k:v for k,v in result.items() if k not in ('request','results')})]
    groups['inputs'] += [['','effective_input','switching_frequency_hz',pole_limit(result['request']['operating_point']['speed_rpm'],result['request'].get('switching_frequency_hz'))['switching_frequency_hz'],'blank_defaults_to_10000_Hz'],
                         ['','effective_input','flux_density_max_T',flux_density_limit(result['request'].get('flux_density_max_T')),'blank_defaults_to_1.8_T'],
                         ['','effective_input','pwm_current_ripple_max_pct',current_ripple_limit(result['request'].get('pwm_current_ripple_max_pct')),'blank_defaults_to_15_pct_phase_fundamental_RMS'],
                         ['','effective_input','torque_ripple_max_pct',torque_ripple_limit(result['request']['operating_point'].get('torque_ripple_max_pct')),'blank_defaults_to_20_pct']]
    for name,rows in groups.items():
        with (folder/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(header)
            contexts={(c['id'],r['label']):f"{r.get('verification_role','nominal')}_{r.get('input_options',{}).get('temperature_C','unknown')}degC_{r.get('design',{}).get('voltage_V','unknown')}V_{r['label']}" for c in result['results'] for r in c['runs']}
            for row in rows:
                model,source,field,value,status=row
                unit,basis=metadata(field)
                evidence=evidence_for(field,name,result.get('stage'))
                condition=contexts.get((model,source),'not_applicable_or_see_field_path')
                if name=='results' and field.startswith('prediction.'):
                    condition=f"{result['request']['temperatures_C'][0]}degC_{min(result['request']['operating_point']['voltages_V'])}V"
                w.writerow([cell(v) for v in row+[unit,basis,condition,evidence]])

