"""Compare provisional screens with saved Native outputs; no new FEA/refit."""
import json
from pathlib import Path
from spm_ripple import predict
from breadloaf_screens import evaluate,reference,ROOT
from study_io import write_json


def run(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);ref=reference();rows=[]
    for name in ('breadloaf_shape_verification_20261104','breadloaf_current_feedback_20261104'):
        folder=ROOT/'outputs'/name
        for row in json.loads((folder/'result.json').read_text(encoding='utf-8'))['outcomes']:
            if row['status']!='completed':continue
            s=json.loads((folder/(row['id']+'_snapshot.json')).read_text(encoding='utf-8'))
            raw=predict(s,2880,480);screen=evaluate(raw,s,s['line_peak_A'],ref)
            v=row['values']
            actual={'phase_fundamental_phasor_rms_V':v.get('Phase Terminal Voltage (rms) [Phasor]'),
                    'copper_loss_W':v['Armature DC Copper Loss (on load)'],'efficiency_pct':v['System Efficiency'],
                    'tooth_local_max_B_T':v['Stator Tooth Flux Density (maximum)'],'yoke_local_max_B_T':v['Stator Back Iron Flux Density (maximum)']}
            rows.append({'id':row['id'],'reference_case':str(folder/row['id']/'result.json')==ref['source'],
                'screens':screen,'native':actual,
                'voltage_difference_pct':100*(screen['phase_fundamental_voltage_rms_V']/actual['phase_fundamental_phasor_rms_V']-1),
                'copper_difference_pct':100*(screen['copper_loss_W']/actual['copper_loss_W']-1),
                'power_balance_residual_W':screen['predicted_input_power_W']-screen['electromagnetic_power_W']-screen['copper_loss_W'],
                'qualified':False})
    result={'schema':'breadloaf-screen-audit-v1','rows':rows,'new_fea_calls':0,'reference':ref,
        'scope':'Local saved-point check only; source R/leakage case is development, not independent validation. B averages and native local maxima differ in definition.',
        'policy':'Guidance only. Retain ripple-best reference and require actual FEA; never certify total efficiency or local peak B from these estimates.'}
    write_json(output/'result.json',result)
    return result


if __name__=='__main__':
    r=run(ROOT/'outputs/breadloaf_screens_check_20261104')
    print(json.dumps([{'id':x['id'],'voltage_difference_pct':x['voltage_difference_pct'],'copper_difference_pct':x['copper_difference_pct'],
        'tooth_average_estimate_T':x['screens']['tooth_section_average_max_B_T'],'native_tooth_max_T':x['native']['tooth_local_max_B_T']} for x in r['rows']],indent=2))
