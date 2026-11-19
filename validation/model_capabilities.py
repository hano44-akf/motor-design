"""Compatibility adapter for current local models; never imports a solver SDK."""
from request_schema import validate_input,normalize_request
from rotor_catalog import preflight,require_execution
from motorcad_adapter import variables


def check_model_support(request,kind='formula'):
    request=normalize_request(request)
    validate_input(request)
    if kind not in ('formula','verification'):raise ValueError('Unknown execution kind')
    review=preflight(request);reasons=list(review['blocking_reasons'])
    if request['connection']!='delta' or request['strands']!=1 or request['paths']!=1:
        reasons.append('Current calibrated family supports delta / 1 strand / 1 path only')
    if request['control'] not in ('FOC_Id0_SVPWM','FOC_MTPA_SVPWM'):reasons.append('Current calibrated family supports FOC ID0 or MTPA / SVPWM only')
    if request['core']!='POSCO | 50PN470' or request['magnet']!='JL Mag Rare-Earth | N48UH':
        reasons.append('Matching performance model required for these materials')
    bounds=request.get('bounds',[[55,100],[20,65],[1,8],[.8,2.2]])
    envelope=[[55,100],[20,65],[1,8],[.8,2.2]]
    if any(b[0]<limit[0] or b[1]>limit[1] for b,limit in zip(bounds,envelope)):
        reasons.append('Current search envelope: OD 55..100 mm, length 20..65 mm, turns 1..8, wire 0.8..2.2 mm')
    if kind=='formula' and request.get('temperatures_C',[20])[0]!=20:reasons.append('Saved formula reference is at 20 C')
    if kind=='verification' and request.get('spm',{}).get('magnetisation','Radial') not in review['capabilities']['verification_directions']:
        reasons.append('Prescribed-current verification is not connected for this rotor/direction')
    return {'schema':'model-support-v1','model_family':'legacy_surface_local_v1','execution_kind':kind,
        'input_valid':True,'supported':not reasons,'blocking_reasons':list(dict.fromkeys(reasons)),
        'configuration':review,'model_units':{'length':'mm','inductance_export':'mH','control_current':'winding phase peak A'},
        'controller_screens':[p['pwm_check'] for p in review['pole_slot_review']],
        'model_validity':{'state':'unverified','independently_qualified':False,
            'reason':'Local scaling family has no independently qualified operating/dimension envelope. Execution support is not accuracy qualification.',
            'requested_conditions':{'speed_rpm':request['operating_point']['speed_rpm'],
                'torque_Nm':request['operating_point']['torque_Nm'],'voltages_V':request['operating_point']['voltages_V'],
                'temperatures_C':request['temperatures_C']},
            'implementation_search_bounds_mm_turns':bounds},
        'scope':'Implementation/model compatibility only; not independent accuracy qualification'}


def validate_for_model(request,kind='verification'):
    request=normalize_request(request)
    support=check_model_support(request,kind)
    if not support['supported']:raise ValueError('; '.join(support['blocking_reasons']))
    require_execution(request,kind)
    variables({**request.get('spm',{}),'temperature_C':request.get('temperatures_C',[20])[0]})
    return request
