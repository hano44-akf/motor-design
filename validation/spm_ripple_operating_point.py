"""Current matching in the linear coenergy prototype; no current-angle sweep.

This is a development model, not a saturation-aware drive feasibility solver.
Targets are electromagnetic torque, not shaft torque. Voltage/loss checks remain
separate. Component scaling is valid only for the uncalibrated linear model.
"""
import math
import numpy as np
from spm_ripple import ripple


def at_current(proxy, reference_line_peak_A, line_peak_A):
    if proxy.get('calibration') != 'none':
        raise ValueError('Raw linear coenergy components required')
    if not math.isfinite(reference_line_peak_A) or reference_line_peak_A <= 0:
        raise ValueError('Positive reference line peak current required')
    if not math.isfinite(line_peak_A) or line_peak_A < 0:
        raise ValueError('Nonnegative line peak current required')
    parts = [np.asarray(proxy[k], dtype=float) for k in ('cogging_Nm', 'mutual_Nm', 'reluctance_Nm')]
    if any(a.ndim != 1 or a.shape != parts[0].shape or len(a) < 8 or not np.all(np.isfinite(a)) for a in parts):
        raise ValueError('Matching finite component arrays required')
    scale = line_peak_A / reference_line_peak_A
    wave = parts[0] + scale * parts[1] + scale ** 2 * parts[2]
    return {**ripple(wave), 'torque_Nm': wave.tolist(), 'line_peak_A': float(line_peak_A),
            'current_scale': scale, 'qualified': False, 'optimization_eligible': False,
            'model': 'linear-coenergy-current-scaling-v1',
            'voltage_verified': False, 'saturation_verified': False}


def match_torque(proxy, reference_line_peak_A, target_electromagnetic_torque_Nm, max_line_peak_A):
    if not math.isfinite(target_electromagnetic_torque_Nm) or target_electromagnetic_torque_Nm <= 0:
        raise ValueError('Positive electromagnetic torque target required')
    if not math.isfinite(max_line_peak_A) or max_line_peak_A <= 0:
        raise ValueError('Positive maximum line peak current required')
    at_current(proxy, reference_line_peak_A, 0)  # Validate components/conventions.
    a, b, c = (float(np.mean(proxy[k])) for k in ('reluctance_Nm', 'mutual_Nm', 'cogging_Nm'))
    c -= target_electromagnetic_torque_Nm
    if abs(a) < 1e-12:
        roots = [-c / b] if abs(b) > 1e-12 else []
    else:
        roots = [float(z.real) for z in np.roots([a, b, c]) if abs(z.imag) < 1e-9]
    allowed = [max(0., s) for s in roots if s >= -1e-10 and s * reference_line_peak_A <= max_line_peak_A + 1e-9]
    if not allowed:
        scales=[0.,max_line_peak_A/reference_line_peak_A]
        if a<0 and 0<-b/(2*a)<scales[-1]:scales.append(-b/(2*a))
        best=max((at_current(proxy,reference_line_peak_A,s*reference_line_peak_A) for s in scales),key=lambda r:r['mean_Nm'])
        return {**best,'status': 'target_not_reached_within_current_limit',
                'target_electromagnetic_torque_Nm': target_electromagnetic_torque_Nm,
                'torque_shortfall_Nm':max(0,target_electromagnetic_torque_Nm-best['mean_Nm']),
                'max_line_peak_A': max_line_peak_A, 'qualified': False, 'optimization_eligible': False}
    result = at_current(proxy, reference_line_peak_A, min(allowed) * reference_line_peak_A)
    return {**result, 'status': 'matched_in_linear_model',
            'target_electromagnetic_torque_Nm': target_electromagnetic_torque_Nm,
            'scope': 'Id=0, unchanged geometry and phase, fixed-temperature linear model only; not FEA validation.'}
