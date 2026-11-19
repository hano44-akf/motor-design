"""Explicit numerical matching policy; not user torque margin or qualification."""
import math
VOLTAGE_RESERVE_FACTOR=.94
TORQUE_MATCH_RELATIVE_TOLERANCE=.01
TORQUE_MATCH_TARGET_FACTOR=1.005
CURRENT_CORRECTION_MIN=.5
CURRENT_CORRECTION_MAX=1.5


def correction_factor(actual,target):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (actual,target)):
        raise ValueError('Positive finite measured and target torque required for correction')
    return max(CURRENT_CORRECTION_MIN,min(CURRENT_CORRECTION_MAX,target*TORQUE_MATCH_TARGET_FACTOR/actual))


def snapshot():
    return {'schema':'numerical-evaluation-policy-v1','voltage_reserve_factor':VOLTAGE_RESERVE_FACTOR,
        'torque_match_relative_upper_tolerance':TORQUE_MATCH_RELATIVE_TOLERANCE,
        'torque_match_target_factor':TORQUE_MATCH_TARGET_FACTOR,
        'current_correction_factor_bounds':[CURRENT_CORRECTION_MIN,CURRENT_CORRECTION_MAX],
        'scope':'Explicit inherited engineering/numerical assumptions, not validated physical error bounds. Required torque lower bound is never relaxed. User capacity margin is separate.'}
