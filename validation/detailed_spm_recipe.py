"""Compile explicit detailed SPM candidates; never launch or solve Motor-CAD.

This is a separate input path, not an extension of the old calibrated surrogate.
Range inputs must be instantiated before they can enter a native recipe.
"""
import copy
import math
from spm_geometry import preview, STATOR_FIELDS
from motorcad_adapter import variables


def compile_recipe(request, point=None):
    resolved=copy.deepcopy(request)
    point=dict(point or {})
    settings=resolved.setdefault('geometry_parameters',{})
    params=resolved.setdefault('spm',{}).setdefault('parameters',{})
    allowed=set(settings)|set(params)|{'airgap_mm'}
    if set(point)-allowed:raise ValueError('Undeclared candidate parameters')
    for group in (settings,params):
        for key,setting in group.items():
            mode=setting.get('mode','auto')
            if mode=='range' and key not in point:raise ValueError('Explicit range point required: '+key)
            if key in point:
                value=point[key]
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Finite candidate value required')
                if mode=='fixed' and value!=setting['value']:raise ValueError('Candidate conflicts with fixed input: '+key)
                if mode=='range' and not setting['min']<=value<=setting['max']:raise ValueError('Candidate outside range: '+key)
                group[key]={'mode':'fixed','value':value}
    gaps=resolved.get('airgap_bounds_mm',[.4,.6])
    gap=point.get('airgap_mm')
    if gap is None:
        if gaps[0]!=gaps[1]:raise ValueError('Explicit airgap_mm required for a gap range')
        gap=gaps[0]
    if isinstance(gap,bool) or not isinstance(gap,(int,float)) or not math.isfinite(gap) or not gaps[0]<=gap<=gaps[1] or abs(gap*10-round(gap*10))>1e-7:
        raise ValueError('Airgap must lie inside bounds on the 0.1 mm grid')
    resolved['airgap_bounds_mm']=[gap,gap]
    result=preview(resolved)
    if len(result['designs'])!=1:raise ValueError('Native recipe requires one explicit pole/slot pair')
    design=result['designs'][0]
    if design['violations']:raise ValueError('Geometry envelope failed: '+', '.join(design['violations']))
    if design['pair']!={'poles':4,'slots':12}:raise ValueError('Native winding mapping pending outside 4 poles / 12 slots')
    active={key for key,setting in params.items() if setting.get('mode')!='auto'}
    pending=active-{'magnet_thickness_mm','pole_arc_ed'}
    if result['rotor_id']=='surface_breadloaf':pending|={'breadloaf_corner_geometry','magnet_reduction_mm'}
    native=dict(design['native_dimension_candidates'])
    native.update({'Shaft_Dia_[F]':native['Shaft_Dia'],'Shaft_Dia_[R]':native['Shaft_Dia']})
    options=copy.deepcopy(resolved['spm']);options.pop('parameters',None)
    options['magnet_arc_deg']=design['magnet_arc_ed']
    native.update(variables(options))
    native.update({'Pole_Number':4,'Slot_Number':12})
    return {'schema':'detailed-spm-native-recipe-v1','rotor_id':result['rotor_id'],
        'native_variables':native,'resolved_request':resolved,'candidate_point':point,
        'default_policy':'Auto dimensions use the declared proportional seed; ranges never use an implicit midpoint.',
        'native_mapping_pending':sorted(pending),'ready_for_readback':not pending,
        'performance_model_connected':False,'full_geometry_qualified':False,
        'performance':{'torque_Nm':None,'efficiency_pct':None,'torque_ripple_pct':None,'max_B_T':None}}


def apply_recipe_checked(mc, recipe):
    """Apply to an already prepared native model. Does not save or run FEA.

    Caller must use a disposable model copy; readback failure may leave partial
    native changes. Geometry envelope success is not magnetic qualification.
    """
    if recipe.get('schema')!='detailed-spm-native-recipe-v1' or not recipe.get('ready_for_readback'):
        raise ValueError('Detailed native mapping is pending')
    expected=recipe['native_variables']
    # Select the template before applying its dimensions.
    keys=['BPMRotor']+[key for key in expected if key!='BPMRotor']
    for key in keys:mc.set_variable(key,expected[key])
    actual={key:mc.get_variable(key) for key in expected}
    for key,value in expected.items():
        if isinstance(actual[key],bool) or not isinstance(actual[key],(int,float)) or not math.isfinite(actual[key]) or abs(actual[key]-value)>1e-7:
            raise RuntimeError('Detailed geometry readback mismatch: '+key)
    return actual
