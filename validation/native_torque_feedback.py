"""Candidate-local current proposal from measured electromagnetic torque.

No ripple calibration and no claim of saturation-aware extrapolation. A new
current always requires native validation. Shaft and electromagnetic targets
must not be mixed in the observations.
"""
import math


def propose_current(observations, target_torque_Nm, max_line_peak_A):
    if not observations:raise ValueError('At least one measured point required')
    def valid(x):return isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)
    if not valid(target_torque_Nm) or target_torque_Nm<=0 or not valid(max_line_peak_A) or max_line_peak_A<=0:
        raise ValueError('Positive finite target and current limit required')
    for point in observations:
        if not valid(point['line_peak_A']) or point['line_peak_A']<=0 or not valid(point['torque_Nm']) or point['torque_Nm']<=0:
            raise ValueError('Positive finite native observations required')
    points=sorted(observations,key=lambda p:abs(p['torque_Nm']-target_torque_Nm))
    a=points[0]
    if abs(a['torque_Nm']-target_torque_Nm)<=1e-12:
        current=a['line_peak_A'];method='already_at_target'
    elif len(points)==1:
        current=a['line_peak_A']*target_torque_Nm/a['torque_Nm'];method='single_point_local_proportional'
    else:
        b=next((p for p in points[1:] if abs(p['line_peak_A']-a['line_peak_A'])>1e-9),None)
        if b is None:raise ValueError('Distinct current observations required for secant')
        slope=(a['torque_Nm']-b['torque_Nm'])/(a['line_peak_A']-b['line_peak_A'])
        if slope<=1e-12:raise ValueError('Nonincreasing native torque; cannot extrapolate current')
        current=a['line_peak_A']+(target_torque_Nm-a['torque_Nm'])/slope;method='two_point_local_secant'
    within=0<current<=max_line_peak_A
    return {'status':'proposed_unverified' if within else 'proposal_outside_current_limit',
            'proposed_line_peak_A':current,'target_torque_Nm':target_torque_Nm,
            'max_line_peak_A':max_line_peak_A,'method':method,'within_current_limit':within,
            'native_verification_required':method!='already_at_target','qualified':False,
            'scope':'Same candidate, control and temperature only. No global torque correction or ripple refit.'}
