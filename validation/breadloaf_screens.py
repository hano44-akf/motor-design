"""Provisional electrical/section-average screens, never FEA qualification.

v = R i + omega_m d(psi_pm + L(alpha)i + L_leak i)/d alpha.
Use total angular derivative for voltage, unlike fixed-current torque derivative.
"""
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from spm_ripple import derivative
from breadloaf_pwm_screen import reference as pwm_reference,evaluate as pwm_evaluate

ROOT=Path(__file__).resolve().parent.parent
REFERENCE=ROOT/'outputs/breadloaf_shape_verification_20261104/breadloaf_search_11_605_2/result.json'


def reference():
    raw=REFERENCE.read_bytes();r=json.loads(raw);v=r['values']
    saved=REFERENCE.parent.parent/(REFERENCE.parent.name+'_snapshot.json')
    native=json.loads(saved.read_text(encoding='utf-8'))['expected_native']
    return {'phase_resistance_ohm':v['Phase Resistance'],
            'phase_leakage_inductance_H':v['Stator Leakage Inductance (Total)']*.001,
            'stacking_factor':v['Lamination Stacking Factor (Stator)'],
            'source':str(REFERENCE),'sha256':hashlib.sha256(raw).hexdigest(),
            'pwm_reference':pwm_reference(),
            'required_native_inputs':{k:native[k] for k in ('Stator_Lam_Dia','Stator_Lam_Length','Stator_Bore','Slot_Depth','Tooth_Width',
                'Pole_Number','Slot_Number','Copper_Diameter','MagTurnsConductor','WindingConnection','ParallelPaths','NumberStrandsHand',
                'StatorConductor_Temperature','StatorLam_Temperature','Magnet_Temperature')},
            'scope':'Fixed winding/geometry/20C local leakage reference; not a general material or loss model.'}


def evaluate(proxy,snapshot,line_peak_A,ref,contract=None):
    state=proxy.get('electromagnetic_state')
    if not state:return {'available':False,'reason':'Saved proxy lacks electromagnetic state; recompute required',
                          'qualified':False,'violation_count':0,'normalized_violation':0}
    if proxy.get('calibration')!='none':raise ValueError('Raw coenergy state required')
    for key,value in ref.get('required_native_inputs',{}).items():
        actual=snapshot['expected_native'].get(key)
        if not isinstance(actual,(int,float)) or not math.isclose(actual,value,abs_tol=1e-8):
            raise ValueError('Electrical reference outside supported template: '+key)
    for key in ('phase_resistance_ohm','phase_leakage_inductance_H','stacking_factor'):
        if not math.isfinite(ref[key]) or ref[key]<=0:raise ValueError('Positive finite electrical reference required')
    factor=line_peak_A/snapshot['line_peak_A'];current=np.asarray(state['reference_phase_current_A'])*factor
    psi=np.asarray(state['pm_flux_linkage_Wb']);L=np.asarray(state['phase_inductance_H'])
    if current.shape!=psi.shape or current.ndim!=2 or current.shape[1]!=3 or L.shape!=(len(current),3,3):
        raise ValueError('Aligned three-phase electromagnetic state required')
    speed=snapshot['expected_native']['ShaftSpeed'];omega=2*math.pi*speed/60
    if not math.isfinite(speed) or speed<=0:raise ValueError('Positive speed required')
    resistance=ref['phase_resistance_ohm'];leak=ref['phase_leakage_inductance_H']
    linkage=psi+np.einsum('nij,nj->ni',L,current)+leak*current
    voltage=resistance*current+omega*derivative(linkage)
    n=len(current);order=snapshot['poles']//2
    fundamental=np.fft.rfft(voltage,axis=0)[order]*2/n/math.sqrt(2)
    fundamental_rms=float(np.max(np.abs(fundamental)))
    copper=float(resistance*np.mean(np.sum(current**2,axis=1)))
    wave=np.asarray(proxy['cogging_Nm'])+factor*np.asarray(proxy['mutual_Nm'])+factor**2*np.asarray(proxy['reluctance_Nm'])
    pem=float(wave.mean())*omega
    eta_upper=100*pem/(pem+copper) if pem>0 else None
    tooth_flux=np.asarray(state['tooth_pm_flux_Wb'])+np.einsum('nqp,np->nq',np.asarray(state['tooth_armature_flux_Wb_per_A']),current)
    g=snapshot['geometry_mm'];length=g['Stator_Lam_Length']/1000;stack=ref['stacking_factor']
    tooth_B=float(np.max(np.abs(tooth_flux)))/(g['Tooth_Width']/1000*length*stack)
    yoke_mm=(g['Stator_Lam_Dia']-g['Stator_Bore'])/2-g['Slot_Depth']
    if yoke_mm<=0:raise ValueError('Positive yoke section required')
    ring=np.cumsum(tooth_flux,axis=1);ring-=((ring.max(axis=1)+ring.min(axis=1))/2)[:,None]
    yoke_B=float(np.max(np.abs(ring)))/(yoke_mm/1000*length*stack)
    bus=min(contract['voltages_V']) if contract else snapshot['expected_native']['DCBusVoltage']
    voltage_limit=bus/math.sqrt(2)  # Delta branch = line-line, linear SVPWM.
    req=contract['requirements'] if contract else {}
    def screen(value,limit,sense='max'):
        deficit=0 if limit is None or value is None else max(0,value-limit) if sense=='max' else max(0,limit-value)
        return {'estimate':value,'limit':limit,'state':'unverified' if value is None else 'not_requested' if limit is None else 'predicted_exceeds' if deficit else 'not_excluded',
                'normalized_violation':deficit/max(abs(limit),1e-12) if limit is not None else 0,
                'qualified':False}
    checks={'fundamental_voltage':screen(fundamental_rms,voltage_limit),
            'efficiency_copper_only_upper_bound':screen(eta_upper,req.get('efficiency_min_pct'),'min'),
            'tooth_section_average_B':screen(tooth_B,req.get('flux_density_max_T')),
            'yoke_section_average_B':screen(yoke_B,req.get('flux_density_max_T'))}
    for name,check in checks.items():
        check['used_for_guidance']=name in ('fundamental_voltage','efficiency_copper_only_upper_bound')
    local={'available':False,'reason':'No local calibrated model or unsupported inputs','qualified':False}
    model_path=ROOT/'outputs/breadloaf_loss_B_validation_20261104/local_loss_B_model.json'
    if contract and model_path.is_file() and all(k in snapshot['expected_native'] for k in ('Slot_Opening','Magnet_Arc_[ED]','MagnetReduction')):
        from breadloaf_local_model import operating_estimate
        model_bytes=model_path.read_bytes()
        local=operating_estimate(json.loads(model_bytes),snapshot,line_peak_A,
                                 float(wave.mean()),tooth_B,yoke_B,copper)
        local['model_sha256']=hashlib.sha256(model_bytes).hexdigest()
        if local['available']:
            checks['local_total_efficiency']=screen(local['efficiency_pct'],req.get('efficiency_min_pct'),'min')
            checks['local_total_efficiency']['used_for_guidance']=True
            for key in ('Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)',
                        'Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)'):
                check=screen(local['values'][key],req.get('flux_density_max_T'))
                check.update(used_for_guidance=True,observed_loo_max_abs_error_T=local['observed_loo_max_abs_error'][key])
                checks['local_'+key]=check
    pwm=pwm_evaluate(snapshot,line_peak_A,contract,ref.get('pwm_reference',{'available':False,'reason':'PWM reference not frozen in search'}))
    checks['pwm_current_ripple']={'state':pwm['state'],'qualified':False,'used_for_guidance':False,'normalized_violation':0}
    return {'available':True,'qualified':False,'checks':checks,'pwm_advisory':pwm,
            'local_calibrated_estimate':local,
            'violation_count':sum(c['state']=='predicted_exceeds' and c['used_for_guidance'] for c in checks.values()),
            'normalized_violation':sum(c['normalized_violation'] for c in checks.values() if c['used_for_guidance']),
            'copper_loss_W':copper,'electromagnetic_power_W':pem,
            'predicted_input_power_W':float(np.mean(np.sum(current*voltage,axis=1))),
            'efficiency_pct':None,'efficiency_copper_only_upper_bound_pct':eta_upper,
            'local_peak_iron_B_T':None,'tooth_section_average_max_B_T':tooth_B,'yoke_section_average_max_B_T':yoke_B,
            'phase_fundamental_voltage_rms_V':fundamental_rms,
            'reference':{'source':ref.get('source'),'sha256':ref.get('sha256')},
            'limitations':['Not excluded is not a verified pass; all estimates require FEA.',
                'Efficiency is a copper-only upper bound, not predicted total efficiency.',
                'Tooth/yoke section-average estimates are not local maximum B; tooth-tip/rotor peak remain unknown.',
                'Section-B is diagnostic only: observed local discrepancies prohibit using it to reject/rank candidates.',
                'Linear iron, approximate slot permeance, fixed local leakage; Delta circulating current/PWM not solved.',
                'Fundamental voltage only, no harmonic/deadtime/device-drop certification.']}
