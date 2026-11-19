"""Manufacturing input resolution; does not enumerate all dimension combinations."""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
import math

STEP_MM = 0.1


def resolution_policy():
    """User clarification: quantise design inputs, retain derived coordinates."""
    return {'schema':'motor-dimension-resolution-policy-v1','design_length_step_mm':STEP_MM,
            'derived_coordinate_mode':'continuous','derived_coordinate_grid_required':False,
            'source':'User clarification: design dimensions use 0.1 mm; automatic coordinates may be continuous',
            'geometry_checks_required':True,'manufacturing_qualified_by_resolution':False}


def mm(value, *, up=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Finite dimension in mm required')
    return float(Decimal(str(value)).quantize(Decimal('0.1'), rounding=ROUND_CEILING if up else ROUND_HALF_UP))


def wire_outer(copper_mm):
    # Preserve at least the old 0.07 mm diametral allowance after rounding.
    return mm(float(Decimal(str(copper_mm))+Decimal('0.07')), up=True)


def grid_bounds(bounds):
    result=[]
    for i,(lo,hi) in enumerate(bounds):
        step=1 if i==2 else STEP_MM
        a=math.ceil(lo/step-1e-9);b=math.floor(hi/step+1e-9)
        if a>b:raise ValueError('No dimension on the 0.1 mm grid within requested bounds')
        result.append((a,b))
    return result
