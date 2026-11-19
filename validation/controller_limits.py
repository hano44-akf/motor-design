"""PWM carrier cycles per fundamental electrical cycle; poles means total poles."""
import math
from evaluation_policy import VOLTAGE_RESERVE_FACTOR

def current_ripple_limit(value=None):
    """Peak-to-peak PWM winding current / reference phase fundamental RMS (%)."""
    if value is None or value=='':return 15.0
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise ValueError('PWM current ripple limit must be positive percent; blank defaults to 15 percent of phase fundamental RMS current')
    return float(value)

def current_ripple_review(run,limit_pct=None):
    limit=current_ripple_limit(limit_pct)
    rms=run['values'].get('Phase Current (rms)')
    usable=isinstance(rms,(int,float)) and not isinstance(rms,bool) and math.isfinite(rms) and rms>0
    return {'limit_pct':limit,'reference':'winding phase fundamental RMS at the prescribed operating point',
            'reference_current_rms_A':rms if usable else None,
            'allowed_current_ripple_pp_A':rms*limit/100 if usable else None,
            'actual_current_ripple_pp_A':None,'passed':None,
            'status':'not_evaluated' if usable else 'reference_current_unavailable',
            'reason':'Prescribed sinusoidal-current FEA has no PWM switching waveform; differential/HF inductance and PWM circuit model are required'}

def torque_ripple_limit(value=None):
    if value is None or value=='':return 20.0
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=20:
        raise ValueError('Torque ripple limit must be between 0 and 20 percent; blank defaults to 20 percent')
    return float(value)

def switching_hz(value=None):
    if value is None or value=='':return 10000.0
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise ValueError('Switching frequency must be positive Hz, or blank for 10000 Hz')
    return float(value)

def pole_limit(speed_rpm,frequency_hz=None,poles=None):
    frequency=switching_hz(frequency_hz)
    if isinstance(speed_rpm,bool) or not isinstance(speed_rpm,(int,float)) or not math.isfinite(speed_rpm) or speed_rpm<=0:
        raise ValueError('Positive speed required for pole limit')
    # Compute in pole pairs so the cap is always even. Equality at 20 is allowed.
    max_pairs=math.floor(math.nextafter(60*frequency/(20*speed_rpm),math.inf))
    result={'switching_frequency_hz':frequency,'minimum_switching_cycles':20,
            'max_even_poles':2*max_pairs,'speed_rpm':speed_rpm,
            'definition':'PWM carrier periods per fundamental electrical period; not transistor edge count'}
    if poles is not None:
        if isinstance(poles,bool) or not isinstance(poles,(int,float)) or not math.isfinite(poles) or poles<2 or poles%2:
            raise ValueError('Pole count must be an even integer >= 2')
        electrical_hz=poles*speed_rpm/120
        result.update(poles=int(poles),electrical_frequency_hz=electrical_hz,
                      switching_cycles_per_electrical_cycle=frequency/electrical_hz,
                      passes=int(poles)<=result['max_even_poles'])
    return result

def inductance_voltage_upper(run, voltage_margin=VOLTAGE_RESERVE_FACTOR):
    """FOC Id=0, SVPWM fundamental winding-phase RMS voltage budget, SI output.

    This is a voltage-budget advisory, not a PWM ripple/current-loop proof.
    PWM lower limit needs differential inductance and a modulation waveform model.
    """
    values=run['values'];readback=run['readback'];bus=run['design']['voltage_V']
    if abs(readback.get('PhaseAdvance',0))>1e-7:
        return {'status':'not_applicable','Lq_upper_H':None,'L_lower_H':None,
                'reason':'Id=0-only inductance budget does not apply to this MTPA/field-weakening operating point; use full dq voltage constraints'}
    required=['Back EMF Phase Voltage (peak) (fundamental)','Phase Resistance','Phase Current (rms)','Fundamental Frequency']
    # Motor-CAD exposes the line-line fundamental for delta as the winding phase.
    emf=values.get(required[0])
    if emf is None and readback.get('WindingConnection')==1:
        emf=values.get('Back EMF Line-Line Voltage (peak) (fundamental)')
    r=values.get(required[1]);current=values.get(required[2]);frequency=values.get(required[3])
    if any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in [emf,r,current,frequency,bus]) or current<=0 or frequency<=0 or bus<=0 or r<0:
        return {'status':'unavailable','reason':'Missing finite fundamental winding-phase electrical data'}
    winding=readback.get('WindingConnection')
    if winding not in (0,1):return {'status':'unavailable','reason':'Unknown winding connection'}
    limit=bus/(math.sqrt(2) if winding==1 else math.sqrt(6))*voltage_margin
    q_voltage=emf/math.sqrt(2)+r*current
    budget=limit**2-q_voltage**2
    return {'status':'voltage_budget_available' if budget>0 else 'no_inductive_voltage_headroom',
            'Lq_upper_H':math.sqrt(budget)/(2*math.pi*frequency*current) if budget>0 else None,
            'winding_phase_rms_voltage_limit_V':limit,'voltage_margin_factor':voltage_margin,
            'L_lower_H':None,'lower_limit_status':'PWM current-ripple target and switching waveform model required',
            'scope':'FOC Id=0/SVPWM, operating-point Lq voltage budget only; not differential/HF inductance or delta circulating-current validation'}
