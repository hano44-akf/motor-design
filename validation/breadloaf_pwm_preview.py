"""Experimental frozen-angle Delta RL / centred SVPWM ripple preview.

No symmetrisation/eigenvalue clipping. Unit closure is checked against Native
CSV precision; inferred diagonal end inductance is an explicit model assumption.
This NEVER replaces prescribed-current FEA's unverified PWM requirement.
"""
import argparse
import csv
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from scipy.linalg import expm
from study_io import write_json


def switching_segments(branch_V,bus_V):
    branch=np.asarray(branch_V,dtype=float)
    if branch.shape!=(3,) or not np.all(np.isfinite(branch)) or not math.isfinite(bus_V) or bus_V<=0:
        raise ValueError('Three finite Delta voltages and positive bus required')
    if abs(branch.sum())>1e-9*max(1,float(abs(branch).max())):raise ValueError('Delta KVL mismatch')
    poles=np.array([branch[0],0.,-branch[1]])
    poles-=(poles.max()+poles.min())/2
    duty=.5+poles/bus_V
    if duty.min()<0 or duty.max()>1:raise ValueError('Requested voltage outside ideal inverter range')
    times=sorted(set([0.,1.]+list(duty/2)+list(1-duty/2)));segments=[]
    for lo,hi in zip(times[:-1],times[1:]):
        if hi<=lo:continue
        mid=(lo+hi)/2;carrier=2*mid if mid<=.5 else 2*(1-mid)
        state=(duty>carrier).astype(float)
        actual=bus_V*(state-np.roll(state,-1))
        segments.append((hi-lo,actual-branch))
    return duty,segments


def periodic_ripple(L_H,R_ohm,bus_V,branch_V,fsw_Hz,samples_per_segment=12):
    L=np.asarray(L_H,dtype=float)
    if L.shape!=(3,3) or not np.all(np.isfinite(L)) or not math.isfinite(R_ohm) or R_ohm<=0 or fsw_Hz<=0:
        raise ValueError('Finite 3x3 inductance, positive phase resistance and frequency required')
    if np.linalg.eigvalsh((L+L.T)/2).min()<=0:raise ValueError('Nonpositive symmetric energy part; no clipping applied')
    if not isinstance(samples_per_segment,int) or samples_per_segment<2:raise ValueError('At least two samples per segment')
    duty,segments=switching_segments(branch_V,bus_V);A=-R_ohm*np.linalg.inv(L);Ts=1/fsw_Hz
    c=np.zeros(3);transforms=[]
    for duration,delta_v in segments:
        dt=duration*Ts;F=expm(A*dt);offset=(np.eye(3)-F)@(delta_v/R_ohm)
        c=F@c+offset;transforms.append((dt,F,offset,delta_v))
    start=np.linalg.solve(np.eye(3)-expm(A*Ts),c);current=start.copy();samples=[]
    q,w=np.polynomial.legendre.leggauss(8);mean=np.zeros(3);second=np.zeros(3)
    for dt,F,offset,delta_v in transforms:
        steady=delta_v/R_ohm
        for t in np.linspace(0,dt,samples_per_segment+1):
            samples.append(steady+expm(A*t)@(current-steady))
        for t,weight in zip((q+1)*dt/2,w*dt/2/Ts):
            point=steady+expm(A*t)@(current-steady);mean+=weight*point;second+=weight*point**2
        current=F@current+offset
    samples=np.asarray(samples)
    return {'phase_ripple_pp_A':np.ptp(samples,axis=0).tolist(),
            'phase_ripple_rms_A':np.sqrt(np.maximum(0,second-mean**2)).tolist(),
            'periodic_residual_A':float(abs(current-start).max()),'mean_ripple_A':mean.tolist(),
            'duty':duty.tolist(),'qualified':False}


def csv_number(path,key):
    for row in csv.reader(path.read_text(encoding='cp1252').splitlines(),delimiter=';'):
        if len(row)>2 and row[0]==key:
            d=Decimal(row[1]);quantum=Decimal(10)**d.as_tuple().exponent
            return float(d),row[2],float(abs(quantum)/2)
    raise ValueError('CSV unit evidence missing: '+key)


def direct_matrix(folder,angle,candidate_id):
    """Case-specific SI interpretation from measured flux/current derivatives.

    Direct response already includes the end term; never add it a second time.
    This numeric unit anchor does not qualify high-frequency motor physics.
    """
    folder=Path(folder);load=lambda name:json.loads((folder/name).read_text(encoding='utf-8'))
    review=load('mapping_review.json');plan=load('plan.json');progress=load('progress.json')
    if (review.get('status')!='central_jacobian_assembled' or
        review.get('response_rows_excitation_columns_explicit') is not True or
        progress.get('data_validated_cases')!=6 or progress.get('completed_fea')!=6 or
        plan['candidate_id']!=candidate_id):raise ValueError('Six validated explicit direct responses required')
    for file_key,hash_key in [('source_snapshot','snapshot_sha256'),('source_model','model_sha256'),('source_database','database_sha256')]:
        if hashlib.sha256(Path(plan[file_key]).read_bytes()).hexdigest()!=plan[hash_key]:
            raise ValueError('Direct response frozen source changed')
    L=np.asarray(review['matrix_native_flux_units_per_A'],float)
    if L.shape!=(len(angle),3,3) or not np.all(np.isfinite(L)) or not np.array_equal(review['angle_ed'],angle):
        raise ValueError('Direct response angle/matrix mismatch')
    if np.diagonal(L,axis1=1,axis2=2).min()<=0 or np.linalg.eigvalsh((L+L.transpose(0,2,1))/2).min()<=0:
        raise ValueError('Nonpositive direct response; no clipping applied')
    anchor=review['unit_and_end_anchor'];common=L.sum(axis=(1,2))/3
    error=float(abs(common-anchor['native_end_inductance_H']).max())
    if error>anchor['native_csv_rounding_H']:raise ValueError('Direct response SI/end anchor mismatch')
    evidence={**anchor,'rpc_graph_unit':'H (case-specific numeric anchor)',
              'end_added_H':0.,'closure_error_H':error,
              'mean_total_self_H':float(np.diagonal(L[:-1],axis1=1,axis2=2).mean())}
    return L[:-1].copy(),evidence


def build(experiment,batch,angle_subdivisions=4,persist=True,direct_folder=None):
    started=time.perf_counter();experiment=Path(experiment).resolve();batch=Path(batch).resolve()
    load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    result=load(experiment/'result.json');plan=load(experiment/'plan.json');original=load(batch/'result.json')
    if Path(plan['source_batch']).resolve()!=batch:raise ValueError('Experiment/source batch mismatch')
    candidate=next(r for r in original['outcomes'] if r['id']==plan['candidate_id'] and r['status']=='completed')
    if hashlib.sha256(Path(plan['source_snapshot']).read_bytes()).hexdigest()!=plan['snapshot_sha256']:
        raise ValueError('Frozen snapshot changed')
    snapshot=load(plan['source_snapshot']);contract=load(batch/'plan.json')['request_contract']
    if snapshot['expected_native']['WindingConnection']!=1 or contract['ui_input_snapshot']['modulation']!='SVPWM':
        raise ValueError('Delta/SVPWM preview only')
    graphs=result['graphs'];angle=np.array(graphs['SelfInductancePh1']['x']);N=len(angle)-1
    if N<6 or not np.allclose(np.diff(angle),360/N) or angle[0]!=0 or angle[-1]!=360:
        raise ValueError('One uniform full electrical cycle including endpoint required')
    L=np.empty((N,3,3));I=np.empty((N,3))
    for i in range(3):
        I[:,i]=graphs[f'SmallSignalInductanceCurrentPh{i+1}']['y'][:-1]
        for j in range(3):
            name=f'SelfInductancePh{i+1}' if i==j else f'MutualInductance{i+1}Ph{j+1}'
            if not np.array_equal(graphs[name]['x'],angle):raise ValueError('Misaligned inductance angles')
            L[:,i,j]=graphs[name]['y'][:-1]
    native_csv=experiment/'case/small_signal.csv'
    self_value,self_unit,self_round=csv_number(native_csv,'Self Inductance')
    end_value,end_unit,end_round=csv_number(native_csv,'Armature End Winding Inductance_(Hanselman)')
    if self_unit!='mH' or end_unit!='mH':raise ValueError('Unexpected Native CSV units')
    active_mean=float(np.diagonal(L,axis1=1,axis2=2).mean())
    error=abs(active_mean+end_value*.001-self_value*.001)
    if error>(self_round+end_round)*.001+1e-12:
        raise ValueError('H graph / mH CSV active+end closure failed')
    raw=L.copy();L+=np.eye(3)[None,:,:]*end_value*.001
    direct_evidence=None
    if direct_folder is not None:
        direct_plan=load(Path(direct_folder)/'plan.json')
        if Path(direct_plan['source_batch']).resolve()!=batch or Path(direct_plan['source_experiment']).resolve()!=experiment:
            raise ValueError('Direct response/source batch mismatch')
        L,direct_evidence=direct_matrix(direct_folder,angle,plan['candidate_id']);raw=L.copy()
    if isinstance(angle_subdivisions,bool) or not isinstance(angle_subdivisions,int) or not 1<=angle_subdivisions<=16:
        raise ValueError('Angle interpolation subdivisions must be 1..16')
    theta=np.radians(angle[:-1]);design=np.column_stack([np.cos(theta),np.sin(theta)])
    coefficients=np.linalg.lstsq(design,I,rcond=None)[0]
    amplitude=np.sqrt((coefficients**2).sum(axis=0))
    preview_angles=np.arange(N*angle_subdivisions)*360/(N*angle_subdivisions)
    interpolated=np.empty((len(preview_angles),3,3))
    for i in range(3):
        for j in range(3):interpolated[:,i,j]=np.interp(preview_angles,angle,np.r_[L[:,i,j],L[0,i,j]])
    theta=np.radians(preview_angles);design=np.column_stack([np.cos(theta),np.sin(theta)])
    unit_current=design@coefficients/amplitude
    derivative=np.column_stack([-np.sin(theta),np.cos(theta)])@coefficients/amplitude
    values=candidate['values'];phi=math.radians(values['Power Factor Angle [Phasor]'])
    voltage=math.sqrt(2)*values['Phase Terminal Voltage (rms) [Phasor]']*(math.cos(phi)*unit_current+math.sin(phi)*derivative)
    khz=contract['ui_input_snapshot'].get('switchingKHz');fsw=10000 if khz in (None,'') else khz*1000
    R=values['Phase Resistance'];reference=values['Phase Current (rms)'];limit=contract['pwm_current_ripple_max_pct']
    rows=[]
    for bus in contract['voltages_V']:
        previews=[];transpose_maximum=-math.inf;transpose_case=None;transpose_index=None
        for index in range(len(preview_angles)):
            # Fit roundoff alone can leave a tiny KVL residual; reject anything larger.
            previews.append(periodic_ripple(interpolated[index],R,bus,voltage[index],fsw))
            alternative=previews[-1] if direct_folder is not None else periodic_ripple(interpolated[index].T,R,bus,voltage[index],fsw)
            if max(alternative['phase_ripple_pp_A'])>transpose_maximum:
                transpose_maximum=max(alternative['phase_ripple_pp_A']);transpose_case=alternative;transpose_index=index
        maximum=max(max(p['phase_ripple_pp_A']) for p in previews)
        nominal_index=max(range(len(previews)),key=lambda k:max(previews[k]['phase_ripple_pp_A']))
        allowed=reference*limit/100;low=min(maximum,transpose_maximum);high=max(maximum,transpose_maximum)
        rows.append({'bus_V':bus,'estimated_max_phase_ripple_pp_A':maximum,
            'estimated_pp_over_phase_rms_pct':100*maximum/reference,
            'transposed_matrix_estimated_max_pp_A':transpose_maximum,
            'matrix_orientation_sensitivity_A':abs(transpose_maximum-maximum),
            'orientation_estimate_range_pp_A':[low,high],
            'allowed_phase_ripple_pp_A':allowed,
            'preview_relation':'orientation_sensitive_limit' if low<=allowed<high else 'estimated_above_limit' if low>allowed else 'estimated_below_limit',
            'actual_pwm_ripple_pp_A':None,'passed':None,'qualified':False,
            'maximum_periodic_residual_A':max(p['periodic_residual_A'] for p in previews),
            'reference_cases':[{'orientation':orientation,'angle_ed':float(preview_angles[index]),
                               'inductance_H':matrix.tolist(),'phase_resistance_ohm':R,'switching_frequency_Hz':fsw,
                               'branch_reference_V':voltage[index].tolist(),'bus_V':bus,
                               'expected_phase_ripple_pp_A':case['phase_ripple_pp_A']}
                              for orientation,index,matrix,case in
                              [('nominal',nominal_index,interpolated[nominal_index],previews[nominal_index]),
                               ('transposed',transpose_index,interpolated[transpose_index].T,transpose_case)]],
            'angle_results':previews})
    report={'schema':'breadloaf-experimental-pwm-preview-v1','candidate_id':plan['candidate_id'],'rows':rows,
        'native_angle_intervals':N,'interpolated_preview_angles':len(preview_angles),
        'unit_evidence':{'rpc_graph_unit':'H','csv_unit':'mH','active_mean_H':active_mean,
                         'end_self_H':end_value*.001,'native_total_self_H':self_value*.001,
                         'closure_error_H':error,'rounding_allowance_H':(self_round+end_round)*.001},
        'matrix_diagnostics':{'raw_reciprocity_max_abs_H':float(abs(raw-raw.transpose(0,2,1)).max()),
            'with_end_symmetric_part_min_eigenvalue_H':float(np.linalg.eigvalsh((L+L.transpose(0,2,1))/2).min()),
            'matrix_qualified':False,'symmetrisation_applied':False},
        'assumptions':['Frozen angle/linear incremental L, periodic linear interpolation between 24 Native bias points; interpolation is not FEA convergence',
            'Native scalar end inductance added to diagonal; end mutual terms assumed zero',
            'MutualInductance{i}Ph{j} interpreted as matrix i,j; transpose ambiguity not resolved',
            'Ideal centred PWM, fundamental Native phasor only, no deadtime/device drops or HF correction',
            'Only switching ripple; no low-frequency Delta circulating-current or full controller solution'],
        'scope':'Development preview, not actual PWM verification or a feasible/infeasible design verdict.',
        'new_native_fea':0,'qualified':False,'pwm_ripple_certified':False,'elapsed_s':time.perf_counter()-started,
        'source_operating_result_sha256':hashlib.sha256((batch/'result.json').read_bytes()).hexdigest(),
        'source_csv_sha256':hashlib.sha256(native_csv.read_bytes()).hexdigest(),
        'source_result_sha256':hashlib.sha256((experiment/'result.json').read_bytes()).hexdigest()}
    if direct_folder is not None:
        legacy=load(experiment/'pwm_preview.json')
        report.update({'schema':'breadloaf-direct-response-pwm-preview-v1',
            'matrix_orientation_resolved':True,'unit_evidence':direct_evidence,
            'source_mapping_sha256':hashlib.sha256((Path(direct_folder)/'mapping_review.json').read_bytes()).hexdigest(),
            'source_legacy_preview_sha256':hashlib.sha256((experiment/'pwm_preview.json').read_bytes()).hexdigest(),
            'assumptions':['Explicit flux-response rows / current-excitation columns; case-specific H interpretation from Native end anchor',
                'Direct response includes end term; zero additional end inductance',
                'Frozen-angle linear incremental L with periodic linear angle interpolation; not angle or perturbation-step convergence',
                'Ideal centred SVPWM, Native fundamental phasor, no deadtime/device drops or HF correction',
                'Switching ripple only; no low-frequency Delta circulating-current/full controller solution']})
        for row,old in zip(rows,legacy['rows']):
            if row['bus_V']!=old['bus_V']:raise ValueError('Legacy voltage comparison mismatch')
            for key in ('transposed_matrix_estimated_max_pp_A','matrix_orientation_sensitivity_A','orientation_estimate_range_pp_A'):
                row.pop(key)
            row['reference_cases']=row['reference_cases'][:1];row['reference_cases'][0]['orientation']='explicit_response'
            row['legacy_nominal_pp_A']=old['estimated_max_phase_ripple_pp_A']
            row['legacy_transposed_pp_A']=old['transposed_matrix_estimated_max_pp_A']
            row['change_from_legacy_nominal_A']=row['estimated_max_phase_ripple_pp_A']-row['legacy_nominal_pp_A']
        if persist:write_json(Path(direct_folder)/'pwm_preview.json',report)
    elif persist:write_json(experiment/'pwm_preview.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--experiment',required=True);p.add_argument('--batch',required=True)
    p.add_argument('--angle-subdivisions',type=int,default=4)
    p.add_argument('--direct-folder')
    a=p.parse_args();r=build(a.experiment,a.batch,a.angle_subdivisions,direct_folder=a.direct_folder)
    print(json.dumps({'unit_evidence':r['unit_evidence'],'matrix_diagnostics':r['matrix_diagnostics'],
                     'rows':[{k:v for k,v in row.items() if k!='angle_results'} for row in r['rows']],'elapsed_s':r['elapsed_s']},indent=2))
