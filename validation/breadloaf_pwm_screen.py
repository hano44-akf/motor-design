"""Point-supported PWM advisory; never extrapolate or certify a candidate.

No empirical model-error bound exists yet. Estimates are shadow checks, excluded
from optimizer penalties and automatic rejection until physical validation.
"""
import hashlib
import json
import math
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'
MATERIAL_KEYS=('core','grades','suffix','control','modulation','connection','eta')
SNAPSHOT_KEYS=('rotor_id','magnetisation','geometry_mm','poles','slots','connection',
               'paths','turns_per_coil','magnet_br_T','magnet_mu_r','coils','magnet_region')


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(folder=DIRECT):
    folder=Path(folder)
    try:
        preview=read(folder/'pwm_preview.json');plan=read(folder/'plan.json')
        batch=Path(plan['source_batch']);snapshot=read(plan['source_snapshot'])
        if preview.get('matrix_orientation_resolved') is not True or preview['unit_evidence'].get('end_added_H')!=0:
            raise ValueError('Explicit direct total matrix required')
        for path,digest in [(folder/'mapping_review.json',preview['source_mapping_sha256']),
                            (plan['source_snapshot'],plan['snapshot_sha256']),
                            (batch/'result.json',preview['source_operating_result_sha256'])]:
            if sha(path)!=digest:raise ValueError('PWM reference source changed')
        contract=read(batch/'plan.json')['request_contract']
        return {'available':True,'source':str(folder/'pwm_preview.json'),'sha256':sha(folder/'pwm_preview.json'),
                'snapshot':{k:snapshot[k] for k in SNAPSHOT_KEYS},
                'native':{k:v for k,v in snapshot['expected_native'].items() if k not in ('DCBusVoltage','PeakCurrent')},
                'line_peak_A':snapshot['line_peak_A'],
                'material_and_control':{k:contract['ui_input_snapshot'].get(k) for k in MATERIAL_KEYS},
                'switching_kHz':contract['ui_input_snapshot'].get('switchingKHz') or 10,
                'phase_rms_reference_A':preview['rows'][0]['allowed_phase_ripple_pp_A']/(contract['pwm_current_ripple_max_pct']/100),
                'rows':[{k:r[k] for k in ('bus_V','estimated_max_phase_ripple_pp_A','estimated_pp_over_phase_rms_pct')} for r in preview['rows']],
                'qualified':False,'model_error_bound_pct':None}
    except (OSError,ValueError,KeyError,TypeError,ZeroDivisionError) as exc:
        return {'available':False,'reason':str(exc),'qualified':False}


def same(a,b):
    # Floating-point serialization tolerance only, not a physical validity range.
    if isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)) and not isinstance(b,bool):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(same(v,b[k]) for k,v in a.items())
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    return a==b


def evaluate(snapshot,line_peak_A,contract,ref=None):
    base={'available':False,'state':'unverified','rows':[],'qualified':False,'passed':None,
          'used_for_guidance':False,'normalized_violation':0.,'model_error_bound_pct':None,
          'automatic_rejection':False,'new_native_fea':0,
          'policy':'Shadow advisory only; no empirical physical-error margin, no optimizer penalty or extrapolation.'}
    if not contract:return {**base,'reason':'Request contract required'}
    limit=contract.get('pwm_current_ripple_max_pct')
    if limit is None:return {**base,'state':'not_requested','reason':'PWM ripple target excluded'}
    if isinstance(limit,bool) or not isinstance(limit,(int,float)) or not math.isfinite(limit) or limit<=0:
        return {**base,'reason':'Positive finite PWM ripple percentage required'}
    ref=reference() if ref is None else ref
    if not ref.get('available'):return {**base,'reason':ref.get('reason','PWM reference unavailable')}
    mismatches=[]
    for k,v in ref['snapshot'].items():
        if not same(snapshot.get(k),v):mismatches.append(k)
    for k,v in ref['native'].items():
        if not same(snapshot.get('expected_native',{}).get(k),v):mismatches.append('native.'+k)
    if not same(line_peak_A,ref['line_peak_A']):mismatches.append('line_peak_A')
    ui=contract.get('ui_input_snapshot',{})
    for k,v in ref['material_and_control'].items():
        if not same(ui.get(k),v):mismatches.append('input.'+k)
    khz=ui.get('switchingKHz');khz=10 if khz in (None,'') else khz
    if not same(khz,ref['switching_kHz']):mismatches.append('switching_kHz')
    voltages=contract.get('voltages_V',[])
    if not voltages or any(not any(same(v,r['bus_V']) for r in ref['rows']) for v in voltages):mismatches.append('voltages_V')
    if mismatches:return {**base,'reason':'Outside measured PWM point support','mismatched_inputs':mismatches,
                          'reference_sha256':ref['sha256']}
    rows=[]
    for bus in voltages:
        row=next(r for r in ref['rows'] if same(bus,r['bus_V']))
        allowed=ref['phase_rms_reference_A']*limit/100
        estimate=row['estimated_max_phase_ripple_pp_A']
        rows.append({**row,'allowed_phase_ripple_pp_A':allowed,'margin_A':allowed-estimate,
                     'margin_percentage_points':limit-row['estimated_pp_over_phase_rms_pct'],
                     'estimated_excess_A':max(0,estimate-allowed),'passed':None})
    return {**base,'available':True,'state':'estimated_exceeds' if any(r['estimated_excess_A']>0 for r in rows) else 'estimated_below_limit',
            'rows':rows,'limit_pct':limit,'reason':'Measured point support; physical PWM validation still pending',
            'reference_sha256':ref['sha256'],'basis':'winding phase switching p-p / fundamental phase RMS'}


def audit(study,output):
    """Write a fresh advisory without changing the original search or ranking."""
    from study_io import write_json
    started=time.perf_counter();study=Path(study).resolve();ref=reference()
    plan=read(study/'plan.json');result=read(study/'result.json');rows=[]
    for finalist in result.get('finalists',[]):
        path=study/(finalist['id']+'_snapshot.json');snapshot=read(path)
        rows.append({'id':finalist['id'],'source_snapshot_sha256':sha(path),
                     'pwm_advisory':evaluate(snapshot,finalist['levels'][-1]['line_peak_A'],plan.get('request_contract'),ref)})
    report={'schema':'breadloaf-pwm-advisory-audit-v1','rows':rows,
            'supported_candidates':sum(r['pwm_advisory']['available'] for r in rows),
            'unverified_candidates':sum(not r['pwm_advisory']['available'] for r in rows),
            'source_result_sha256':sha(study/'result.json'),'source_plan_sha256':sha(study/'plan.json'),
            'ranking_changed':False,'native_fea_calls':0,'qualified':False,'elapsed_s':time.perf_counter()-started}
    write_json(Path(output),report);return report


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=audit(a.study,a.output)
    print(json.dumps({k:v for k,v in r.items() if k!='rows'},indent=2))
