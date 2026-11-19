"""Saved-run assessment independent of native solver execution."""
import math
from controller_limits import pole_limit,inductance_voltage_upper,torque_ripple_limit,current_ripple_review
from flux_limits import flux_density_limit,flux_density_review
from dimension_grid import mm,wire_outer
from operating_control import control_policy
from result_policy import requirement,summarize_requirements,shortfall_summary

def assess_run(run,request,capacity_evidence=None):
    v=run['values'];op=request['operating_point'];bus=run['design']['voltage_V']
    def num(k):
        x=v.get(k)
        return x if isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) else None
    hard={}
    for k in ['Shaft Torque','System Efficiency','Line-Line Terminal Voltage (peak)','Line-Line Terminal Voltage (rms)','Copper Slot Fill (Slot Area)','Shaft Speed']:
        hard['finite_'+k]=num(k) is not None
    hard['positive_torque']=num('Shaft Torque') is not None and v['Shaft Torque']>0
    hard['efficiency_range']=num('System Efficiency') is not None and 0<v['System Efficiency']<=100
    hard['peak_voltage']=num('Line-Line Terminal Voltage (peak)') is not None and 0<=v['Line-Line Terminal Voltage (peak)']<=bus
    # Conservative total RMS screen in addition to the sampled waveform peak screen.
    hard['rms_voltage']=num('Line-Line Terminal Voltage (rms)') is not None and 0<=v['Line-Line Terminal Voltage (rms)']<=bus/math.sqrt(2)
    hard['slot_fill']=num('Copper Slot Fill (Slot Area)') is not None and 0<v['Copper Slot Fill (Slot Area)']<=.5
    hard['speed_applied']=num('Shaft Speed') is not None and abs(v['Shaft Speed']-op['speed_rpm'])<1e-5
    hard['solver_voltage_flag_clear']=run.get('voltage_limit_exceeded') is False
    if run.get('dimension_resolution_mm')==.1:
        hard['wire_fits_slot']=wire_outer(run['design']['wire_diameter_mm'])<=run.get('geometry_mm',{}).get('Slot_Opening',mm(3*run['design']['diameter_mm']/130))
    else:
        hard['wire_fits_slot']=run['design']['wire_diameter_mm']+.07<=3*run['design']['diameter_mm']/130
    hard['input_mapping_checked']='BPMRotor' in run['readback'] and 'Magnetization' in run['readback']
    if 'phase_advance_deg' in run['design']:
        hard['control_angle_applied']=abs(run['readback'].get('PhaseAdvance',float('inf'))-run['design']['phase_advance_deg'])<1e-6
    if 'airgap_mm' in run['design']:
        hard['airgap_applied']=abs(run.get('geometry_mm',{}).get('Airgap',float('inf'))-run['design']['airgap_mm'])<1e-6
    try:
        controller=pole_limit(op['speed_rpm'],request.get('switching_frequency_hz'),run['readback'].get('Pole_Number'))
        hard['switching_cycles_at_least_20']=controller.get('passes',False)
    except ValueError:
        controller={'status':'invalid'};hard['switching_cycles_at_least_20']=False
    capacity=run.get('verification_role')=='capacity'
    target=op['torque_Nm']*(1+op.get('torque_margin_pct',0)/100) if capacity else op['torque_Nm']
    targets={'capacity_torque_Nm' if capacity else 'torque_Nm':(target,num('Shaft Torque'),'min')}
    if op.get('torque_margin_pct',0)>0 and not capacity:
        # A nominal operating-point solve is not evidence of capacity margin.
        actual=None
        if capacity_evidence is not None:
            from verification_conditions import run_key
            if run_key(capacity_evidence)==('capacity',*run_key(run)[1:]):
                actual=capacity_evidence.get('values',{}).get('Shaft Torque')
                if isinstance(actual,bool) or not isinstance(actual,(int,float)) or not math.isfinite(actual):actual=None
        targets['capacity_torque_Nm']=(op['torque_Nm']*(1+op['torque_margin_pct']/100),actual,'min')
    targets['torque_ripple_max_pct']=(torque_ripple_limit(op.get('torque_ripple_max_pct')),num('Torque Ripple (MsVw) [%]'),'max')
    flux=flux_density_review(run,request.get('flux_density_max_T'))
    targets['flux_density_max_T']=(flux['limit_T'],flux['maximum_T'],'max')
    if op.get('efficiency_min_pct') is not None:targets['efficiency_pct']=(op['efficiency_min_pct'],num('System Efficiency'),'min')
    for field,key in [('current_density_max_A_mm2','Armature Conductor Current Density'),('dc_current_max_A','DC Supply Current (mean)')]:
        if op.get(field) is not None:targets[field]=(op[field],num(key),'max')
    deficits={k:None if a is None else max(0,t-a) if sense=='min' else max(0,a-t) for k,(t,a,sense) in targets.items()}
    pwm=current_ripple_review(run,request.get('pwm_current_ripple_max_pct'))
    known_targets_met=all(hard.values()) and all(d==0 for d in deficits.values())
    unverified=['pwm_current_ripple'] if pwm['passed'] is None else []
    if flux['missing_regions']:unverified.append('iron_flux_density')
    if control_policy(request)['current_control']=='MTPA' or control_policy(request)['field_weakening']:
        unverified.append('nonlinear_control_optimality')
    if run.get('readback',{}).get('PhaseAdvance',0)>1e-6:unverified.append('demagnetization_under_negative_Id')
    requirements={key:requirement(actual,limit,sense) for key,(limit,actual,sense) in targets.items()}
    for key in unverified:requirements[key]=requirement(None,1)
    summary=summarize_requirements(requirements)
    # Missing targets (for example ripple) must also appear in the shared state.
    unverified=list(dict.fromkeys(unverified+summary['unverified']))
    return {'physical_screens_pass':all(hard.values()),'known_targets_met':known_targets_met,'target_met':known_targets_met and not unverified,'requirements_fully_verified':not unverified,
            'requirement_details':requirements,'requirement_summary':summary,
            'unverified_requirements':unverified,'pwm_current_ripple':pwm,
            'flux_density':flux,
            'checks':hard,'shortfalls':deficits,'controller_limits':controller,'inductance_review':inductance_voltage_upper(run),
            'effective_torque_ripple_limit_pct':torque_ripple_limit(op.get('torque_ripple_max_pct')),
            'scope':'Prescribed-current electromagnetic calculation; inverter switching/circulating current, mesh convergence and demagnetization remain separate. Thermal and structural analyses excluded by user.'}

def normalized_shortfall(run,request):
    """Compatibility score for old selectors; unknown ranking is migrated later.

    New callers use deficit_summary: it never invents a numeric unknown value.
    """
    summary=deficit_summary(run,request)
    return summary['known_normalized_shortfall']+1e6*len(summary['unverified_requirements'])


def deficit_summary(run,request):
    op=request['operating_point']
    references={**op,'efficiency_pct':op.get('efficiency_min_pct') or 100,
                'capacity_torque_Nm':op['torque_Nm']*(1+op.get('torque_margin_pct',0)/100),
                'torque_ripple_max_pct':torque_ripple_limit(op.get('torque_ripple_max_pct')),
                'flux_density_max_T':flux_density_limit(request.get('flux_density_max_T'))}
    return shortfall_summary(run['assessment']['shortfalls'],references)

