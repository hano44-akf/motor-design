"""Per-condition predicted requirements. Missing evidence is never a pass."""
from result_policy import requirement,summarize_requirements
from controller_limits import current_ripple_limit,torque_ripple_limit
from flux_limits import flux_density_limit
from evaluation_policy import VOLTAGE_RESERVE_FACTOR


def assess_prediction(prediction,request):
    op=request['operating_point'];bus=min(op['voltages_V']);temp=request['temperatures_C'][0]
    limits={'torque_Nm':(op['torque_Nm'],'min','estimated_shaft_torque_Nm'),
        'efficiency_pct':(op.get('efficiency_min_pct'),'min','efficiency_pct'),
        'dc_current_max_A':(op.get('dc_current_max_A'),'max','estimated_dc_current_A'),
        'current_density_max_A_mm2':(op.get('current_density_max_A_mm2'),'max','estimated_current_density_A_mm2'),
        'voltage_peak_V':(bus*VOLTAGE_RESERVE_FACTOR,'max','estimated_terminal_peak_V'),
        'flux_density_max_T':(flux_density_limit(request.get('flux_density_max_T')),'max',None),
        'torque_ripple_max_pct':(torque_ripple_limit(op.get('torque_ripple_max_pct')),'max',None),
        'pwm_current_ripple_max_pct':(current_ripple_limit(request.get('pwm_current_ripple_max_pct')),'max',None)}
    if op.get('torque_margin_pct',0)>0:
        limits['capacity_torque_Nm']=(op['torque_Nm']*(1+op['torque_margin_pct']/100),'min',None)
    conditions=[]
    for ti,t in enumerate(request['temperatures_C']):
        for vi,v in enumerate(op['voltages_V']):
            evaluated=t==temp and v==bus
            items={key:{**requirement(prediction.get(field) if evaluated and field else None,
                    (v*VOLTAGE_RESERVE_FACTOR if key=='voltage_peak_V' else limit),sense),'evidence':'local_formula_prediction'}
                for key,(limit,sense,field) in limits.items()}
            if prediction.get('operating_control',{}).get('phase_advance_deg',0)>1e-6:
                items['demagnetization_under_negative_Id']={**requirement(None,1),'evidence':'not_evaluated'}
            summary=summarize_requirements(items)
            conditions.append({'condition_id':f't{ti}_v{vi}','temperature_C':t,'voltage_V':v,
                'evaluated_by_formula':evaluated,'requirements':items,'summary':summary})
    violated=any(c['summary']['violated'] for c in conditions)
    missing=any(c['summary']['unverified'] for c in conditions)
    physical=prediction['physical_screen_pass']
    return {'schema':'formula-requirements-v1','conditions':conditions,
        'evaluated_condition':{'temperature_C':temp,'voltage_V':bus},
        'predicted_evaluated_requirements_met':physical and not violated,
        'predicted_all_active_met':False if violated or not physical else None if missing else True,
        'verification_complete':False,'model_validity':'unverified','qualified':False,
        'dc_current_basis':'Motor input power / Vdc, ideal inverter efficiency 100 percent; inverter losses excluded',
        'scope':'Predicted numbers only at reference temperature and minimum bus. Other conditions and B/ripple/PWM remain unverified.'}
