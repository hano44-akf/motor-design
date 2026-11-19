"""Independent fixed-grid RK4 / direct triangle-carrier numerical check.

Imports neither the preview's switch event schedule nor its matrix exponential
solver. Shares the frozen RL inputs, hence cannot qualify physical assumptions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from study_io import write_json


def simulate(case,steps=16384):
    if isinstance(steps,bool) or not isinstance(steps,int) or steps<128:raise ValueError('At least 128 fixed steps required')
    L=np.asarray(case['inductance_H'],float);R=case['phase_resistance_ohm'];frequency=case['switching_frequency_Hz']
    bus=case['bus_V'];reference=np.asarray(case['branch_reference_V'],float)
    if L.shape!=(3,3) or not np.all(np.isfinite(L)) or not np.all(np.isfinite([R,frequency,bus])) or R<=0 or frequency<=0 or bus<=0:
        raise ValueError('Finite RL circuit and positive frequency/bus required')
    if reference.shape!=(3,) or not np.all(np.isfinite(reference)):raise ValueError('Three finite Delta branch voltages required')
    if abs(reference.sum())>1e-9:raise ValueError('Delta KVL mismatch')
    # Independent pole reconstruction via the Delta incidence matrix.
    C=np.array([[1.,-1.,0.],[0.,1.,-1.],[-1.,0.,1.]])
    poles=np.linalg.lstsq(C,reference,rcond=None)[0]
    offset=-.5*(poles.max()+poles.min());duty=.5+(poles+offset)/bus
    if duty.min()<0 or duty.max()>1:raise ValueError('Unsupported inverter command')
    def forcing(t):
        carrier=1-np.abs(2*t-1)
        switches=(carrier[:,None]<duty[None,:]).astype(float)
        voltage=bus*switches@C.T-reference
        return np.linalg.solve(L,voltage.T).T,voltage
    t=np.arange(steps)/steps;u0,v0=forcing(t);um,vm=forcing(t+.5/steps);u1,v1=forcing(t+1/steps)
    h=1/(steps*frequency);A=np.linalg.solve(L,-R*np.eye(3));Z=A*h;I=np.eye(3)
    Z2=Z@Z;Z3=Z2@Z;P=I+Z+Z2/2+Z3/6+Z3@Z/24
    # Algebraically collected classical RK4 stages, no matrix exponentials.
    K0=h/6*(I+Z+Z2/2+Z3/4);Km=h/6*(4*I+2*Z+Z2/2);K1=h/6*I
    kicks=u0@K0.T+um@Km.T+u1@K1.T
    forced=np.zeros(3)
    for kick in kicks:forced=P@forced+kick
    transition=np.linalg.matrix_power(P,steps);start=np.linalg.solve(I-transition,forced)
    current=start.copy();wave=np.empty((steps+1,3));wave[0]=current
    for i,kick in enumerate(kicks):current=P@current+kick;wave[i+1]=current
    return {'steps_per_carrier':steps,'phase_ripple_pp_A':np.ptp(wave,axis=0).tolist(),
            'mean_ripple_A':np.trapezoid(wave,dx=1/steps,axis=0).tolist(),
            'carrier_mean_voltage_error_V':((v0+4*vm+v1).mean(axis=0)/6).tolist(),
            'periodic_residual_A':float(np.max(abs(current-start))),
            'qualified':False}


def review(experiment):
    started=time.perf_counter();experiment=Path(experiment).resolve()
    source=experiment/'pwm_preview.json';preview=json.loads(source.read_text(encoding='utf-8'));rows=[]
    for bus_row in preview['rows']:
        for case in bus_row['reference_cases']:
            reference_runs=[simulate(case,n) for n in (4096,16384,65536)]
            expected=np.array(case['expected_phase_ripple_pp_A']);final=np.array(reference_runs[-1]['phase_ripple_pp_A'])
            errors=[float(np.max(abs(np.array(r['phase_ripple_pp_A'])-expected))) for r in reference_runs]
            rows.append({'bus_V':case['bus_V'],'orientation':case['orientation'],'angle_ed':case['angle_ed'],
                         'matrix_exponential_phase_pp_A':expected.tolist(),'fixed_grid_RK4_phase_pp_A':final.tolist(),
                         'phase_pp_max_abs_difference_A':errors[-1],
                         'last_grid_change_A':float(np.max(abs(final-np.array(reference_runs[-2]['phase_ripple_pp_A'])))),
                         'runs':reference_runs,'numerical_error_by_grid_A':errors,
                         'physical_model_qualified':False})
    report={'schema':'breadloaf-independent-pwm-numerical-check-v1','cases':rows,
            'maximum_phase_pp_difference_A':max(r['phase_pp_max_abs_difference_A'] for r in rows),
            'maximum_last_grid_change_A':max(r['last_grid_change_A'] for r in rows),
            'scope':f'{len(rows)} selected worst-angle/orientation cases, same frozen-angle RL inputs. Numerical implementation check only; not Native/physical PWM validation.',
            'numerical_acceptance_tolerance_A':None,'physical_model_qualified':False,'matrix_orientation_resolved':preview.get('matrix_orientation_resolved',False),
            'new_native_fea':0,'elapsed_s':time.perf_counter()-started,
            'source_preview_sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
    write_json(experiment/'pwm_reference_review.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--experiment',required=True);a=p.parse_args();r=review(a.experiment)
    print(json.dumps({k:v for k,v in r.items() if k!='cases'},indent=2))
