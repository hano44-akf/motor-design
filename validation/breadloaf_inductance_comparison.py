"""Compare the raw coenergy L with explicitly labelled Native derivatives.

Align electrical origins using currents only. Never fit L or ripple, permute
phases, symmetrise matrices, or qualify a geometry family from one point.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from breadloaf_pwm_preview import direct_matrix,periodic_ripple,csv_number
from breadloaf_pwm_screen import same
from breadloaf_screens import reference
from study_io import write_json


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def align_by_current(proxy_angle_ed,proxy_current,native_angle_ed,native_current):
    def coefficients(angle,current):
        t=np.radians(angle);design=np.c_[np.cos(t),np.sin(t)]
        c=np.linalg.lstsq(design,np.asarray(current),rcond=None)[0]
        amplitude=np.linalg.norm(c,axis=0)
        if np.min(amplitude)<=1e-9:raise ValueError('Nonzero three phase fundamental required')
        return c/amplitude
    c=coefficients(proxy_angle_ed,proxy_current);d=coefficients(native_angle_ed,native_current)
    delta=math.atan2(float(np.sum(c[1]*d[0]-c[0]*d[1])),float(np.sum(c*d)))
    rotation=np.array([[math.cos(delta),math.sin(delta)],[-math.sin(delta),math.cos(delta)]])
    error=float(np.max(abs(rotation@c-d)))
    if error>1e-8:raise ValueError('Current phase sequence cannot be matched by one angle-origin shift')
    return math.degrees(delta),error


def interpolate_cycles(angle_ed,matrices,target_ed,shift_ed):
    angle=np.asarray(angle_ed,float);matrices=np.asarray(matrices,float)
    if matrices.shape!=(len(angle),3,3) or not np.all(np.isfinite(matrices)) or angle[0]!=0 or np.any(np.diff(angle)<=0):
        raise ValueError('Finite uniformly sampled full mechanical-cycle matrices required')
    step=angle[1]-angle[0]
    if not np.allclose(np.diff(angle),step) or not math.isclose((angle[-1]+step)/360,round((angle[-1]+step)/360)):
        raise ValueError('Integer electrical cycles required')
    cycles=round((angle[-1]+step)/360);n=round(360/step)
    if n*cycles!=len(angle):raise ValueError('Electrical cycles not aligned to samples')
    target=(np.asarray(target_ed)+shift_ed)%360;out=[]
    for cycle in range(cycles):
        values=matrices[cycle*n:(cycle+1)*n]
        sampled=np.empty((len(target),3,3))
        for i in range(3):
            for j in range(3):sampled[:,i,j]=np.interp(target,np.r_[np.arange(n)*step,360],np.r_[values[:,i,j],values[0,i,j]])
        out.append(sampled)
    out=np.asarray(out)
    return out.mean(axis=0),float(np.ptp(out,axis=0).max())


def diagnostics(estimate,measured):
    error=estimate-measured
    # Compare the balanced-current subspace as well as individual entries.
    Q=np.array([[1/math.sqrt(2),1/math.sqrt(6)],[-1/math.sqrt(2),1/math.sqrt(6)],[0,-2/math.sqrt(6)]])
    balanced=np.einsum('ai,nab,bj->nij',Q,error,Q)
    return {'mean_self_H':float(np.diagonal(estimate,axis1=1,axis2=2).mean()),
            'common_mode_max_abs_H':float(abs(estimate.sum(axis=(1,2))/3).max()),
            'matrix_rmse_H':float(np.sqrt(np.mean(error**2))),
            'maximum_entry_error_H':float(abs(error).max()),
            'balanced_subspace_error_spectral_max_H':float(np.linalg.norm(balanced,ord=2,axis=(1,2)).max()),
            'minimum_symmetric_energy_eigenvalue_H':float(np.linalg.eigvalsh((estimate+estimate.transpose(0,2,1))/2).min())}


def build(direct,study,persist=True):
    started=time.perf_counter();direct=Path(direct).resolve();study=Path(study).resolve()
    plan=read(direct/'plan.json');candidate=plan['candidate_id'];preview=read(direct/'pwm_preview.json')
    if preview['source_mapping_sha256']!=sha(direct/'mapping_review.json'):raise ValueError('Stale direct PWM preview')
    snapshot=read(plan['source_snapshot']);proxy_snapshot=read(study/(candidate+'_snapshot.json'))
    for key in ('geometry_mm','coils','magnet_region','rotor_id','magnetisation','magnet_br_T','magnet_mu_r'):
        if not same(snapshot[key],proxy_snapshot[key]):raise ValueError('Proxy physical source mismatch: '+key)
    for key,value in snapshot['expected_native'].items():
        if key not in ('PeakCurrent','DCBusVoltage') and not same(value,proxy_snapshot['expected_native'].get(key)):
            raise ValueError('Proxy Native source mismatch: '+key)
    source=study/(candidate+'_high_resolution.json');proxy=read(source)['raw_proxy']
    if proxy['calibration']!='none':raise ValueError('Uncalibrated proxy required')
    review=read(direct/'mapping_review.json');native_angles=np.array(review['angle_ed'])
    measured,evidence=direct_matrix(direct,native_angles,candidate)
    plus=next(c for c in plan['cases'] if c['id']=='phase1_plus')
    minus=next(c for c in plan['cases'] if c['id']=='phase1_minus')
    native_current=(np.asarray(plus['expected_phase_current_A'])+np.asarray(minus['expected_phase_current_A']))[:-1]/2
    proxy_angle=np.array(proxy['angle_mechanical_deg'])*(snapshot['poles']//2)
    state=proxy['electromagnetic_state']
    shift,alignment_error=align_by_current(proxy_angle,state['reference_phase_current_A'],native_angles[:-1],native_current)
    targets=np.arange(preview['interpolated_preview_angles'])*360/preview['interpolated_preview_angles']
    active,cycle_spread=interpolate_cycles(proxy_angle,state['phase_inductance_H'],targets,shift)
    direct_L=np.empty_like(active)
    for i in range(3):
        for j in range(3):direct_L[:,i,j]=np.interp(targets,native_angles,np.r_[measured[:,i,j],measured[0,i,j]])
    ref=reference();leak=ref['phase_leakage_inductance_H'];end=evidence['native_end_inductance_H']
    native_csv=Path(plan['source_batch'])/candidate/(candidate+'.csv')
    components={};rounding={}
    for label,key in [('slot','Stator Slot Leakage Inductance'),('differential','Stator Differential Leakage Inductance'),
                      ('end','Armature End Winding Inductance_(Hanselman)'),('total','Stator Leakage Inductance (Total)')]:
        number,unit,quantum=csv_number(native_csv,key)
        if unit!='mH':raise ValueError('Native leakage component unit mismatch')
        components[label]=number*.001;rounding[label]=quantum*.001
    closure=abs(components['slot']+components['differential']+components['end']-components['total'])
    if closure>sum(rounding.values()):raise ValueError('Native leakage component closure failed')
    variants={'raw_active_only':active,'active_plus_native_end_only':active+np.eye(3)*end,
              'existing_screen_active_plus_reference_leakage':active+np.eye(3)*leak,
              'active_plus_same_case_total_leakage':active+np.eye(3)*components['total'],
              'hypothesis_active_plus_native_slot_and_end':active+np.eye(3)*(components['slot']+components['end'])}
    native_coef=np.linalg.lstsq(np.c_[np.cos(np.radians(native_angles[:-1])),np.sin(np.radians(native_angles[:-1]))],native_current,rcond=None)[0]
    native_coef/=np.linalg.norm(native_coef,axis=0)
    batch=Path(plan['source_batch']);outcome=next(r for r in read(batch/'result.json')['outcomes'] if r['id']==candidate)
    values=outcome['values'];phi=math.radians(values['Power Factor Angle [Phasor]']);t=np.radians(targets)
    v=math.sqrt(2)*values['Phase Terminal Voltage (rms) [Phasor]']*(math.cos(phi)*np.c_[np.cos(t),np.sin(t)]@native_coef+math.sin(phi)*np.c_[-np.sin(t),np.cos(t)]@native_coef)
    fsw=preview['rows'][0]['reference_cases'][0]['switching_frequency_Hz'];R=values['Phase Resistance'];rows=[]
    for name,L in variants.items():
        stats=diagnostics(L,direct_L);buses=[]
        if stats['minimum_symmetric_energy_eigenvalue_H']>0:
            for saved in preview['rows']:
                pp=max(max(periodic_ripple(matrix,R,saved['bus_V'],command,fsw)['phase_ripple_pp_A']) for matrix,command in zip(L,v))
                native_pp=saved['estimated_max_phase_ripple_pp_A']
                buses.append({'bus_V':saved['bus_V'],'estimated_phase_pp_A':pp,'direct_matrix_phase_pp_A':native_pp,
                              'difference_A':pp-native_pp,'relative_difference_pct':100*(pp/native_pp-1),
                              'actual_pwm_passed':None,'qualified':False})
        rows.append({'variant':name,'matrix_diagnostics':stats,'pwm_rows':buses,
                     'pwm_solver_status':'computed' if buses else 'blocked_nonpositive_energy_no_clipping',
                     'common_mode_note':'Raw coenergy excludes leakage and has a common-mode nullspace; full Delta branch RL inversion is unsupported.' if name=='raw_active_only' else None,
                     'used_for_optimizer_guidance':False})
    report={'schema':'breadloaf-low-cost-inductance-comparison-v1','candidate_id':candidate,'rows':rows,
            'native_direct_mean_self_H':float(np.diagonal(direct_L,axis1=1,axis2=2).mean()),
            'current_only_alignment_shift_ed':shift,'normalized_current_coefficient_error':alignment_error,
            'proxy_electrical_cycle_matrix_spread_H':cycle_spread,'angles':len(targets),
            'reference_leakage_H':leak,'native_end_H':end,
            'native_leakage_components_H':components,'leakage_component_closure_error_H':closure,
            'leakage_component_rounding_allowance_H':sum(rounding.values()),
            'component_policy':'Native slot/end reused only for one-point diagnosis. Excluding differential leakage is a hypothesis, not a qualified general formula.',
            'scope':'One geometry and bias point; matrix/ripple-model comparison, not actual PWM verification or cross-geometry validation.',
            'fitted_inductance_parameters':0,'qualified':False,'family_extension_allowed':False,
            'new_native_fea':0,'elapsed_s':time.perf_counter()-started,
            'source_mapping_sha256':sha(direct/'mapping_review.json'),'source_preview_sha256':sha(direct/'pwm_preview.json'),
            'source_proxy_sha256':sha(source),'source_proxy_snapshot_sha256':sha(study/(candidate+'_snapshot.json')),
            'source_native_csv_sha256':sha(native_csv),
            'source_files':{str(path):sha(path) for path in (source,study/(candidate+'_snapshot.json'),native_csv,Path(ref['source']))},
            'reference_electrical_result_sha256':ref['sha256'],
            'policy':'No phase permutation, matrix symmetrisation, eigenvalue clipping, fitted correction or automatic PWM rejection.'}
    if persist:write_json(direct/'low_cost_matrix_review.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);p.add_argument('--study',required=True);a=p.parse_args()
    print(json.dumps(build(a.direct,a.study),indent=2))
