"""Bounded shaft-torque current solve inside the local surrogate domain.

Current interval is the intersection of the development convex hull and the
user limit at fixed geometry. No current-angle/full-current-grid sweep.
"""
import math
import numpy as np
from scipy.optimize import linprog,brentq,minimize_scalar
from breadloaf_local_model import CENTER,SCALE
from spm_ripple_operating_point import at_current,match_torque
from breadloaf_screens import evaluate


def current_interval(model,snapshot,max_current):
    if snapshot['expected_native']['ShaftSpeed']!=model['reference_speed_rpm']:return None
    if not math.isfinite(max_current) or max_current<=0:raise ValueError('Positive current limit required')
    n=snapshot['expected_native']
    geom=(np.array([n[k] for k in ('Slot_Opening','Magnet_Arc_[ED]','MagnetReduction')])-CENTER[:3])/SCALE[:3]
    training=np.asarray(model['training_coordinates']);a=np.vstack([np.ones(len(training)),training[:,:3].T]);b=np.r_[1.,geom]
    low=linprog(training[:,3],A_eq=a,b_eq=b,bounds=(0,None),method='highs')
    high=linprog(-training[:,3],A_eq=a,b_eq=b,bounds=(0,None),method='highs')
    if not low.success or not high.success:return None
    lo=max(0.,float(low.fun*SCALE[3]+CENTER[3]));hi=min(max_current,float(-high.fun*SCALE[3]+CENTER[3]))
    if lo>hi+1e-8:return None
    if hi-lo>2e-5:lo+=1e-5;hi-=1e-5
    return (lo,max(lo,hi))


def solve(proxy,snapshot,target_shaft_torque_Nm,max_line_peak_A,ref,contract,model):
    if not math.isfinite(target_shaft_torque_Nm) or target_shaft_torque_Nm<=0:raise ValueError('Positive shaft torque required')
    interval=current_interval(model,snapshot,max_line_peak_A)
    cache={}
    def point(current):
        key=float(current)
        if key not in cache:
            screens=evaluate(proxy,snapshot,key,ref,contract)
            local=screens.get('local_calibrated_estimate',{})
            if not local.get('available'):raise ValueError('Current point outside calibrated domain')
            cache[key]=(local['shaft_torque_Nm'],screens)
        return cache[key]
    def unverified(reason):
        fallback=match_torque(proxy,snapshot['line_peak_A'],target_shaft_torque_Nm,max_line_peak_A)
        return {**fallback,'raw_current_matching_status':fallback['status'],'status':'shaft_matching_unverified',
                'shaft_control_status':'unverified','shaft_control_reason':reason,'control_torque_basis':'electromagnetic_lower_bound_only',
                'target_shaft_torque_Nm':target_shaft_torque_Nm,'shaft_control_evaluations':len(cache)}
    if interval is None:return unverified('No calibrated current interval at this geometry/speed within user current limit')
    lo,hi=interval
    try:
        low_t=point(lo)[0];high_t=point(hi)[0]
        if low_t>=target_shaft_torque_Nm:
            chosen=lo;matched=True;method='minimum_domain_current_already_above_minimum_target'
        elif high_t>=target_shaft_torque_Nm:
            chosen=brentq(lambda i:point(i)[0]-target_shaft_torque_Nm,lo,hi,xtol=1e-7)
            matched=True;method='bounded_brent_root'
        else:
            candidates=[lo,hi]
            if hi-lo>1e-7:
                r=minimize_scalar(lambda i:-point(i)[0],bounds=(lo,hi),method='bounded',options={'maxiter':24,'xatol':1e-5})
                candidates.append(float(r.x))
            peak=max(candidates,key=lambda i:point(i)[0])
            if point(peak)[0]>=target_shaft_torque_Nm:
                chosen=brentq(lambda i:point(i)[0]-target_shaft_torque_Nm,lo,peak,xtol=1e-7)
                matched=True;method='bounded_peak_then_brent'
            else:chosen=peak;matched=False;method='best_within_domain_and_current_limit'
        shaft,screens=point(chosen)
    except ValueError as exc:return unverified(str(exc))
    raw=at_current(proxy,snapshot['line_peak_A'],chosen)
    return {**raw,'status':'matched_shaft_in_local_model' if matched else 'shaft_target_not_reached_within_domain',
            'control_torque_basis':'shaft_local_model','shaft_control_status':'model_target_met' if matched else 'model_target_unmet',
            'target_shaft_torque_Nm':target_shaft_torque_Nm,'predicted_shaft_torque_Nm':shaft,
            'shaft_torque_shortfall_Nm':max(0,target_shaft_torque_Nm-shaft),
            'torque_shortfall_Nm':max(0,target_shaft_torque_Nm-shaft),
            'calibrated_current_interval_A':list(interval),'shaft_control_evaluations':len(cache),
            'shaft_control_method':method,'model_screens':screens,'qualified':False,
            'scope':'Local surrogate shaft target, not actual FEA target satisfaction. Ripple remains raw prototype.'}
