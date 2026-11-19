"""Bounded steady-state dq control prediction; never an FEA/demagnetization proof.

Currents/voltages are winding phase PEAK, inductances H, p is pole pairs.
Gamma=atan2(-Id,Iq), matching Motor-CAD positive phase advance.
"""
import math
from scipy.optimize import brentq, minimize_scalar
from evaluation_policy import VOLTAGE_RESERVE_FACTOR,TORQUE_MATCH_TARGET_FACTOR


def control_policy(request):
    op=request.get('operating_point',{})
    policy=op.get('current_control', 'MTPA' if request.get('control')=='FOC_MTPA_SVPWM' else 'ID0')
    weakening=op.get('field_weakening',False)
    if policy not in ('ID0','MTPA'):raise ValueError('current_control must be ID0 or MTPA')
    if not isinstance(weakening,bool):raise ValueError('field_weakening must be boolean')
    return {'current_control':policy,'field_weakening':weakening}


def airgap_bounds(request):
    bounds=request.get('airgap_bounds_mm')
    if bounds is None:bounds=[.4,.6]
    if not isinstance(bounds,(list,tuple)) or len(bounds)!=2:raise ValueError('airgap_bounds_mm requires [min,max]')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in bounds) or bounds[0]>bounds[1]:
        raise ValueError('Airgap must be positive: min <= max (mm)')
    lo=math.ceil(bounds[0]*10-1e-8);hi=math.floor(bounds[1]*10+1e-8)
    if lo>hi:raise ValueError('Airgap range contains no 0.1 mm point')
    return [lo/10,hi/10]


def solve_control(*,torque_Nm,speed_rpm,pole_pairs,psi_Wb,ld_H,lq_H,resistance_ohm,
                  voltage_peak_V,policy='ID0',field_weakening=False,current_peak_max_A=None,
                  torque_factor=1.):
    numeric=[torque_Nm,speed_rpm,pole_pairs,psi_Wb,ld_H,lq_H,resistance_ohm,voltage_peak_V,torque_factor]
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in numeric):raise ValueError('Finite dq inputs required')
    if min(torque_Nm,pole_pairs,psi_Wb,ld_H,lq_H,voltage_peak_V,torque_factor)<=0 or min(speed_rpm,resistance_ohm)<0:raise ValueError('Invalid dq model')
    if policy not in ('ID0','MTPA'):raise ValueError('Invalid current control policy')
    if current_peak_max_A is not None and (not math.isfinite(current_peak_max_A) or current_peak_max_A<0):raise ValueError('Nonnegative phase peak current limit required')
    omega=2*math.pi*speed_rpm/60*pole_pairs;delta=ld_H-lq_H
    k=1.5*pole_pairs*torque_factor
    def iq_for(id_):return torque_Nm/(k*(psi_Wb+delta*id_))
    evaluations=0
    def point(id_):
        nonlocal evaluations
        evaluations+=1;iq=iq_for(id_)
        vd=resistance_ohm*id_-omega*lq_H*iq
        vq=resistance_ohm*iq+omega*(psi_Wb+ld_H*id_)
        return iq,math.hypot(id_,iq),math.hypot(vd,vq)
    id_=0.
    if policy=='MTPA' and abs(delta)>1e-12:
        def mtpa_id(iq):return 2*delta*iq*iq/(psi_Wb+math.sqrt(psi_Wb**2+4*delta*delta*iq*iq))
        upper=torque_Nm/(k*psi_Wb)
        def torque_residual(q):
            nonlocal evaluations
            evaluations+=1
            return k*(psi_Wb+delta*mtpa_id(q))*q-torque_Nm
        iq=brentq(torque_residual,0.,upper,xtol=1e-10)
        id_=mtpa_id(iq)
    base_id=id_;base_iq,_,base_v=point(id_);active=False
    if field_weakening and base_v>voltage_peak_V*(1+1e-9):
        # Full flux cancellation is only a numerical search bound, NOT a safe
        # magnet demagnetization limit. That remains a mandatory separate review.
        lower=-psi_Wb/ld_H;upper=min(0.,id_)
        answer=minimize_scalar(lambda d:point(d)[2]**2,bounds=(lower,upper),method='bounded',options={'xatol':1e-8,'maxiter':70})
        dmin=min((lower,float(answer.x),upper),key=lambda d:point(d)[2])
        if point(dmin)[2]<=voltage_peak_V and dmin<base_id:
            id_=brentq(lambda d:point(d)[2]-voltage_peak_V,dmin,base_id,xtol=1e-9)
        else:id_=dmin
        active=id_<base_id-1e-8
    iq,current,voltage=point(id_)
    v_ok=voltage<=voltage_peak_V*(1+1e-7)
    i_ok=current_peak_max_A is None or current<=current_peak_max_A*(1+1e-7)
    return {'policy':policy,'field_weakening_allowed':field_weakening,'field_weakening_active':active,
            'id_phase_peak_A':id_,'iq_phase_peak_A':iq,'phase_peak_A':current,
            'phase_advance_deg':math.degrees(math.atan2(-id_,iq)),
            'voltage_phase_peak_V':voltage,'voltage_phase_peak_limit_V':voltage_peak_V,
            'voltage_passed':v_ok,'current_passed':i_ok,'feasible':v_ok and i_ok,
            'model_evaluations':evaluations,'base_id_phase_peak_A':base_id,'base_iq_phase_peak_A':base_iq,
            'ld_H':ld_H,'lq_H':lq_H,'psi_pm_Wb':psi_Wb,'resistance_ohm':resistance_ohm,
            'current_limit_supplied':current_peak_max_A is not None,
            'scope':'Constant-parameter fundamental dq prediction; not PWM, ripple, demagnetization or saturated-map validation'}


def control_from_run(run,request,voltage=None,temp=None):
    """Use saved FEA winding-phase parameters at their actual operating point."""
    if run.get('readback',{}).get('WindingConnection')!=1:
        raise ValueError('Saved-run control adapter requires Delta winding connection')
    v=run['values'];design=run['design'];op=request['operating_point'];p=run['readback'].get('Pole_Number',4)/2
    hz=v['Fundamental Frequency'];emf=v['Back EMF Line-Line Voltage (peak) (fundamental)']
    # Current automated family is delta: winding branch voltage = line-line.
    psi=emf/(2*math.pi*hz);ip=v['Phase Current (peak)']
    angle=math.radians(run.get('operating_control',{}).get('phase_advance_deg',run['readback'].get('PhaseAdvance',0)))
    ld=v['D Axis Inductance']*.001;lq=v['Q Axis Inductance']*.001
    raw_torque=1.5*p*(psi*ip*math.cos(angle)+(ld-lq)*(-ip*math.sin(angle))*ip*math.cos(angle))
    factor=v['Shaft Torque']/raw_torque if raw_torque>0 else 1.
    phase_limit=None
    density=op.get('current_density_max_A_mm2')
    if density is not None:phase_limit=density*math.pi*design['wire_diameter_mm']**2/4*math.sqrt(2)
    resistance=v['Phase Resistance']
    ref_temp=run.get('input_options',{}).get('temperature_C',20)
    if temp is not None and temp!=ref_temp:
        resistance*=max(.05,1+.00393*(temp-ref_temp))
    result=solve_control(torque_Nm=op['torque_Nm']*TORQUE_MATCH_TARGET_FACTOR,speed_rpm=op['speed_rpm'],pole_pairs=p,
        psi_Wb=psi,ld_H=ld,lq_H=lq,resistance_ohm=resistance,
        voltage_peak_V=(voltage if voltage is not None else design['voltage_V'])*VOLTAGE_RESERVE_FACTOR,
        current_peak_max_A=phase_limit,torque_factor=factor,**{'policy':control_policy(request)['current_control'],
        'field_weakening':control_policy(request)['field_weakening']})
    result['parameter_source_label']=run['label']
    result['temperature_model']='Resistance-only temperature correction; flux/inductance need FEA feedback'
    return result
