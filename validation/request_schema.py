"""Model-independent input validation and a versioned SI domain snapshot.

The UI currently submits spm-study-v1. It is adapted without modifying input.
motor-study-domain-v1 is an internal snapshot, not a new public input format.
"""
import copy
import math
from controller_limits import current_ripple_limit,torque_ripple_limit,switching_hz
from flux_limits import flux_density_limit
from operating_control import airgap_bounds,control_policy
from rotor_catalog import resolve_rotor,pole_slot_pairs,validate_parameters,manufacturing_rule,default_magnetisation


def normalize_request(request):
    """Fill explicit compatibility defaults without mutating the caller's input."""
    if not isinstance(request,dict):raise ValueError('Request must be an object')
    result=copy.deepcopy(request)
    result.setdefault('temperatures_C',[20])
    result.setdefault('bounds',[[55,100],[20,65],[1,8],[.8,2.2]])
    options=result.setdefault('spm',{})
    if not isinstance(options,dict):raise ValueError('spm must be an object')
    rotor=resolve_rotor(options)
    options.setdefault('shape',rotor['input_value'])
    options.setdefault('magnetisation',default_magnetisation(options))
    op=result.get('operating_point')
    if isinstance(op,dict):
        op.setdefault('torque_margin_pct',0)
        voltages=op.get('voltages_V')
        if isinstance(voltages,list) and voltages and all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in voltages):
            op['voltages_V']=sorted(set(voltages))
    return result


def number(value,name,minimum=None,maximum=None,strict=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError('Finite numeric value required: '+name)
    if minimum is not None and (value<=minimum if strict else value<minimum):raise ValueError('Value below allowed domain: '+name)
    if maximum is not None and value>maximum:raise ValueError('Value above allowed domain: '+name)
    return value


def validate_input(request):
    """Validate syntax/physical domains, independently of available calibration."""
    if not isinstance(request,dict) or request.get('schema')!='spm-study-v1':raise ValueError('Expected spm-study-v1 request')
    for key in ('core','magnet'):
        if not isinstance(request.get(key),str) or not request[key].strip():raise ValueError('Material name required: '+key)
    if request.get('connection') not in ('delta','star'):raise ValueError('Connection must be delta or star')
    for key in ('strands','paths'):
        value=number(request.get(key),key,1)
        if int(value)!=value:raise ValueError('Positive integer required: '+key)
    if request.get('control') not in ('FOC_Id0_SVPWM','FOC_MTPA_SVPWM','six_step'):
        raise ValueError('Unknown control specification')
    if request.get('dimension_resolution_mm',.1)!=.1:raise ValueError('Design dimension resolution is fixed at 0.1 mm')
    for key in ('detailed_review','open_motorcad_after'):
        if not isinstance(request.get(key,False),bool):raise ValueError(key+' must be boolean')
    op=request.get('operating_point')
    if not isinstance(op,dict):raise ValueError('Operating point required')
    for key in ('torque_Nm','speed_rpm'):number(op.get(key),key,0,strict=True)
    number(op.get('torque_margin_pct',0),'torque_margin_pct',0)
    eta=op.get('efficiency_min_pct')
    if eta is not None:number(eta,'efficiency_min_pct',0,100)
    for key in ('current_density_max_A_mm2','dc_current_max_A'):
        if op.get(key) is not None:number(op[key],key,0)
    voltages=op.get('voltages_V')
    if not isinstance(voltages,list) or not voltages:raise ValueError('DC voltage conditions required')
    for value in voltages:number(value,'voltages_V',0,strict=True)
    nominal=op.get('nominal_voltage_V')
    if nominal is not None:
        number(nominal,'nominal_voltage_V',0,strict=True)
        # A saved-design verification may evaluate only a subset of buses while
        # retaining the original design's nominal voltage as metadata.
        if not request.get('formula_source_job') and not min(voltages)<=nominal<=max(voltages):raise ValueError('Nominal voltage must lie within voltage conditions')
    temps=request.get('temperatures_C',[20])
    if not isinstance(temps,list) or not temps:raise ValueError('Temperature conditions required')
    for value in temps:number(value,'temperatures_C',-273.15,strict=True)
    bounds=request.get('bounds',[[55,100],[20,65],[1,8],[.8,2.2]])
    if not isinstance(bounds,list) or len(bounds)!=4:raise ValueError('Four design bounds required')
    for i,bound in enumerate(bounds):
        if not isinstance(bound,(tuple,list)) or len(bound)!=2:raise ValueError('Invalid bounds')
        lo,hi=[number(v,'bounds',0,strict=True) for v in bound]
        if lo>hi:raise ValueError('Reversed bounds')
        factor=1 if i==2 else 10
        if i==2 and any(not float(v).is_integer() for v in bound):raise ValueError('Turns bounds must be integers')
        if math.ceil(lo*factor-1e-8)>math.floor(hi*factor+1e-8):raise ValueError('Range contains no permitted design grid point')
    rounds=number(request.get('search_rounds',2),'search_rounds',1,4)
    if int(rounds)!=rounds:raise ValueError('search_rounds must be an integer')
    control_policy(request);airgap_bounds(request)
    current_ripple_limit(request.get('pwm_current_ripple_max_pct'))
    torque_ripple_limit(op.get('torque_ripple_max_pct'))
    flux_density_limit(request.get('flux_density_max_T'))
    switching_hz(request.get('switching_frequency_hz'))
    rotor=resolve_rotor(request.get('spm',{}))
    direction=request.get('spm',{}).get('magnetisation',default_magnetisation(request.get('spm',{})))
    if direction not in ('Radial','Parallel','Template'):raise ValueError('Unknown magnetisation')
    validate_parameters(request.get('spm',{}),manufacturing_rule(request));pole_slot_pairs(request)
    if 'geometry_parameters' in request:
        from spm_geometry import validate_settings
        validate_settings(request['geometry_parameters'])
    if request.get('skew') is not None or request.get('skew_deg') is not None:raise ValueError('Skew is excluded from this program')
    return request


def domain_snapshot(request):
    """Convert dimensional search variables to SI; preserve electrical bases."""
    request=normalize_request(request)
    validate_input(request)
    bounds=request.get('bounds',[[55,100],[20,65],[1,8],[.8,2.2]])
    variables=[]
    for name,unit,bound,index in zip(('stator_outer_diameter','stack_length','turns_per_coil','wire_diameter'),('m','m','1','m'),bounds,range(4)):
        factor=1 if index==2 else .001
        variables.append({'id':name,'unit':unit,'min':bound[0]*factor,'max':bound[1]*factor,'step':1 if index==2 else .0001})
    gap=airgap_bounds(request)
    variables.append({'id':'airgap','unit':'m','min':gap[0]*.001,'max':gap[1]*.001,'step':.0001})
    op=copy.deepcopy(request['operating_point'])
    rotor=resolve_rotor(request.get('spm',{}))
    return {'schema':'motor-study-domain-v1','source_schema':request['schema'],
        'rotor':{'id':rotor['id'],'magnetisation':request.get('spm',{}).get('magnetisation','Radial' if rotor['direction_policy']=='explicit' else 'Template')},
        'pole_slot_candidates':pole_slot_pairs(request),'materials':{'core':request['core'],'magnet':request['magnet']},
        'winding':{key:request[key] for key in ('connection','strands','paths')},
        'operating_points':[{'id':'op1',**op}],
        'temperatures_K':[v+273.15 for v in request.get('temperatures_C',[20])],
        'search_variables':variables,'control':({'drive':'six_step','current_control':None,'field_weakening':False,'implemented':False}
            if request['control']=='six_step' else {'drive':request['control'],**control_policy(request)}),
        'detailed_geometry_parameters_mm':copy.deepcopy(request.get('geometry_parameters',{})),
        'limits':{'flux_density_max_T':flux_density_limit(request.get('flux_density_max_T')),
            'torque_ripple_max_pct':torque_ripple_limit(op.get('torque_ripple_max_pct')),
            'pwm_current_ripple_max_pct':current_ripple_limit(request.get('pwm_current_ripple_max_pct')),
            'switching_frequency_Hz':switching_hz(request.get('switching_frequency_hz'))},
        'electrical_basis':'Control solver uses winding-phase peak current/voltage. No implicit phase/line or RMS/peak conversion.',
        'scope':'Versioned domain snapshot; legacy numerical model retains its explicitly declared mm units.'}
