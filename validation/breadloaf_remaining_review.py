"""Offline drive screening and explicit remaining work; never certify PWM."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from controller_limits import current_ripple_review,pole_limit
from study_io import write_json

SOURCES={
 'defined_currents':'https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v261/en/Motor-CAD_UG/MotorCAD/topics/defined_currents.html',
 'inductance':'https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v261/en/Motor-CAD_UG/MotorCAD/topics/selfandmutualinductance.html',
 'modulation':'https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v261/en/Motor-CAD_UG/MotorCAD/topics/pwm_modulation.html'}


def assess(snapshot,outcome,contract):
    n=snapshot['expected_native'];v=outcome['values']
    if n['WindingConnection']!=1:raise ValueError('Delta winding reference required')
    if contract['ui_input_snapshot'].get('modulation')!='SVPWM':raise ValueError('SVPWM-only drive screening')
    def positive(x):return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>0
    voltages=contract['voltages_V']
    if not voltages or not all(positive(x) for x in voltages):raise ValueError('Positive finite bus voltages required')
    # Native winding-phase phasor RMS is line-line RMS for this Delta case.
    phasor=v.get('Phase Terminal Voltage (rms) [Phasor]')
    native_bus=v.get('DC Bus Voltage');voltage_rows=[];remaining=[]
    for bus in sorted(set(voltages)):
        same=positive(native_bus) and math.isclose(bus,native_bus,abs_tol=1e-8,rel_tol=0)
        limit=bus/math.sqrt(2)
        voltage_rows.append({'bus_V':bus,'ideal_linear_line_line_rms_limit_V':limit,
            'saved_delta_terminal_phasor_rms_V':phasor if positive(phasor) else None,
            'ideal_phasor_utilisation':phasor/limit if positive(phasor) else None,
            'native_at_this_bus':same,
            'native_voltage_limit_exceeded':outcome.get('voltage_limit_exceeded') if same else None,
            'status':'native_at_this_bus' if same else 'screen_only_not_native_verified',
            'qualified':False})
        if not same:remaining.append({'id':'voltage_'+str(bus),'kind':'additional_bus_voltage','bus_V':bus,
            'status':'unverified','execution':'optional_same_current_native_confirmation',
            'reason':'Saved operating-point voltage is reused only for ideal headroom screening; no new Native/PWM result at this bus.'})
    current=current_ripple_review(outcome,contract.get('pwm_current_ripple_max_pct'))
    khz=contract['ui_input_snapshot'].get('switchingKHz')
    fsw=10000 if khz in (None,'') else khz*1000
    carrier=pole_limit(n['ShaftSpeed'],fsw,n['Pole_Number'])
    remaining.append({'id':'pwm_current_ripple','kind':'pwm_circuit_verification','status':'unverified',
        'execution':'method_and_sdk_mapping_pending','native_run_count':None,
        'required_data':['Small Signal phase self/mutual inductance versus rotor angle at bias current',
                         'Delta zero-sequence/circulating-current model',
                         'PWM switching sequence and time-domain branch currents',
                         'Inverter device/deadtime settings or explicit ideal-inverter assumption'],
        'reason':'Static D/Q inductance and prescribed sinusoidal currents are insufficient for PWM ripple certification.'})
    return {'candidate_id':snapshot['id'],'voltage_screen':voltage_rows,'pwm_reference':current,
            'carrier_check':carrier,'remaining_items':remaining,'remaining_validation_item_count':len(remaining),
            'confirmed_additional_native_runs':0,'optional_same_current_voltage_runs':len(voltage_rows)-sum(r['native_at_this_bus'] for r in voltage_rows),
            'native_experiments_with_unestimated_count':1,'automatic_fea_started':False,
            'scope':'Ideal SVPWM phasor headroom advisory only; no inverter drops, deadtime, harmonics or PWM-current verification.'}


def build(folder):
    folder=Path(folder).resolve();load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    plan=load(folder/'plan.json');result=load(folder/'result.json')
    contract=plan.get('request_contract')
    if not contract:raise ValueError('Saved shaft request contract required')
    cases={c['id']:c for c in plan['cases']};rows=[]
    for outcome in result['outcomes']:
        if outcome['status']!='completed':continue
        name=outcome['id'];path=folder/(name+'_snapshot.json')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=cases[name]['snapshot_sha256']:
            raise ValueError('Frozen snapshot changed')
        rows.append(assess(load(path),outcome,contract))
    report={'schema':'breadloaf-remaining-drive-review-v1','cases':rows,'sources':SOURCES,
            'native_result_sha256':hashlib.sha256((folder/'result.json').read_bytes()).hexdigest(),
            'new_native_fea':0,'full_verification_complete':False,
            'policy':'Do not use this advisory to replace unverified requirements with passed.'}
    experiment_folder=Path(__file__).resolve().parent.parent/'outputs/breadloaf_small_signal_20261105'
    if (experiment_folder/'plan.json').is_file():
        experiment=load(experiment_folder/'plan.json')
        if experiment.get('source_batch')==str(folder):
            experiment_progress=load(experiment_folder/'progress.json') if (experiment_folder/'progress.json').is_file() else {}
            for row in rows:
                row['confirmed_additional_native_runs']=max(0,experiment['planned_fea']-experiment_progress.get('completed_fea',0))
                row['small_signal_completed_native_runs']=experiment_progress.get('completed_fea',0)
                row['small_signal_experiment_folder']=str(experiment_folder)
                row['small_signal_note']='Extraction completion is counted separately from pending physical PWM qualification; subsequent physical validation count remains unestimated.'
    write_json(folder/'remaining_drive_review.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True);a=p.parse_args()
    print(json.dumps(build(a.batch),indent=2))
