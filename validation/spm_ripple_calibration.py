"""Shared component-gain/phase calibration on development data only.

Never fit direct ripple ratios or clip output toward the acceptance threshold.
Independent candidate-level FEA remains required after fitting.
"""
import numpy as np
from scipy.optimize import least_squares
from spm_ripple import ripple,acceptance

COMPONENTS=('cogging_Nm','mutual_Nm','reluctance_Nm')


def transform(proxy,parameters):
    arrays=np.array([proxy[k] for k in COMPONENTS],dtype=float)
    n=arrays.shape[1];order=np.fft.fftfreq(n,1/n)
    gain=np.asarray(parameters[:3]);phase=parameters[3];decay=parameters[4]
    factors=np.exp(1j*order*phase-decay*np.abs(order))
    spectrum=(gain[:,None]*np.fft.fft(arrays,axis=1)).sum(axis=0)*factors
    return np.fft.ifft(spectrum).real


def fit(rows):
    if len(rows)<6:raise ValueError('At least six development records required')
    targets=[]
    for row in rows:
        actual=np.asarray(row['actual_waveform_Nm'],dtype=float)
        if len(actual)!=len(row['proxy']['torque_Nm']) or not np.all(np.isfinite(actual)):raise ValueError('Aligned full-mechanical-cycle samples required')
        targets.append(actual)
    def residual(parameters):
        errors=[]
        for row,actual in zip(rows,targets):
            predicted=transform(row['proxy'],parameters)
            # Ripple must not disappear in a mean-torque-dominated least-squares
            # loss. Fit mean and AC waveform as separate, normalized responses.
            errors.append(np.sqrt(len(actual))*(predicted.mean()-actual.mean())/max(abs(float(actual.mean())),.1))
            errors.extend(((predicted-predicted.mean())-(actual-actual.mean()))/max(float(actual.std()),.01))
        # Mild regularization does not encode a desired ripple or pass rate.
        return np.r_[errors,.01*(parameters[:3]-1)]
    fits=[]
    for shift in (0,np.pi/24,-np.pi/24):
        fits.append(least_squares(residual,[1,1,1,shift,0],
            bounds=([-3,.1,-3,-np.pi/6,-.015],[3,2,3,np.pi/6,.06]),max_nfev=200))
    result=min(fits,key=lambda r:float(np.sum(r.fun*r.fun)))
    return {'schema':'spm-component-calibration-v1','parameters':result.x.tolist(),
        'parameter_names':['cogging_gain','mutual_gain','reluctance_gain','mechanical_phase_rad','spectral_decay_per_order'],
        'training_ids':[r['id'] for r in rows],'training_shapes':sorted({r['rotor_id'] for r in rows}),
        'training_rmse_relative':float(np.sqrt(np.mean(result.fun[:-3]**2))),
        'optimizer_success':bool(result.success),'qualified':False,
        'gain_policy':'Signed cogging/reluctance corrections are development residuals, not verified physical material constants.',
        'scope':'Development fit only, no independent validation. Flat transfer is unverified.',
        'training_comparison':[{'id':r['id'],'predicted_ripple_pct':ripple(transform(r['proxy'],result.x))['ripple_pct'],
            'actual_ripple_pct':ripple(a)['ripple_pct']} for r,a in zip(rows,targets)]}


def apply(proxy,calibration,*,allow_unseen_shape=False):
    rotor=proxy.get('rotor_id')
    seen=rotor is not None and rotor in calibration['training_shapes']
    if not seen and not allow_unseen_shape:
        raise ValueError('Calibration has no development data for rotor shape: '+str(rotor)+
                         '. Cross-family transfer requires explicit experimental opt-in.')
    wave=transform(proxy,np.array(calibration['parameters']));summary=ripple(wave)
    return {**proxy,'raw_ripple_pct':proxy['ripple_pct'],**summary,'torque_Nm':wave.tolist(),
        'calibration':'spm-component-calibration-v1','calibration_training_ids':calibration['training_ids'],
        'qualified':False,'optimization_eligible':False,
        'calibration_domain':'trained_shape_unqualified' if seen else 'unseen_shape_experimental_transfer',
        'acceptance':acceptance(summary['ripple_pct'],None),
        'scope':'Component/phase corrected development model; independent FEA required.'}
