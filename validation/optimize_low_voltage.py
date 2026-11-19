"""Bounded differential-evolution search on an explicitly FEA-calibrated surrogate.
FEA validation is separate; predicted candidates are never labelled validated here.
"""
from pathlib import Path
import json,math,random,time
OUT=Path(__file__).resolve().parent/'optimization_12V_50PN470'
from controller_limits import pole_limit
from dimension_grid import mm,wire_outer,grid_bounds
from scipy.optimize import differential_evolution
from evaluation_policy import VOLTAGE_RESERVE_FACTOR,TORQUE_MATCH_RELATIVE_TOLERANCE,TORQUE_MATCH_TARGET_FACTOR,correction_factor,snapshot as evaluation_policy_snapshot
from operating_control import solve_control,airgap_bounds
from study_io import write_json
P_REQ=.5*3500*math.pi/30
def optimize(calibration_file='pilot_arc120.json',suffix='', efficiency_target=88.0, dc_voltage=9.0, torque_target=.5, speed_rpm=3500, search_bounds=None, output_dir=None, switching_frequency_hz=None,record_evaluated_points=False,airgap_bounds_mm=None,current_control='ID0',field_weakening=False,current_density_max_A_mm2=None,dc_current_max_A=None):
 if efficiency_target is not None and (isinstance(efficiency_target,bool) or not isinstance(efficiency_target,(int,float)) or not math.isfinite(efficiency_target) or not 0<=efficiency_target<=100):
  raise ValueError('Efficiency target must be None or finite percent in [0,100]')
 if isinstance(dc_voltage,bool) or not math.isfinite(dc_voltage) or dc_voltage<=0:raise ValueError('Positive DC voltage required')
 if dc_current_max_A is not None and (isinstance(dc_current_max_A,bool) or not isinstance(dc_current_max_A,(int,float)) or not math.isfinite(dc_current_max_A) or dc_current_max_A<0):raise ValueError('DC current maximum must be finite nonnegative A or None')
 out=Path(output_dir) if output_dir else OUT
 power_required=torque_target*speed_rpm*math.pi/30
 if torque_target<=0 or speed_rpm<=0:raise ValueError('Positive torque and speed required')
 t=time.perf_counter();pilot=json.loads((out/calibration_file).read_text(encoding='utf-8'));v=pilot['values'];b=pilot['design']
 # This geometry/loss scaling family is calibrated only for 4 poles / 12 slots.
 # Reject direct callers too: changing frequency alone cannot generalize it.
 native=pilot.get('readback',{})
 if native.get('Pole_Number',4)!=4 or native.get('Slot_Number',12)!=12:
  raise ValueError('Topology-specific geometry and performance calibration required; current optimizer supports 4 poles / 12 slots only')
 controller=pole_limit(speed_rpm,switching_frequency_hz,pilot.get('readback',{}).get('Pole_Number',4))
 if not controller['passes']:raise ValueError('Pole count excluded: fewer than 20 PWM periods per electrical cycle')
 D0,L0,N0,W0=b['diameter_mm'],b['length_mm'],b['turns_per_coil'],b['wire_diameter_mm']
 kt=v['Shaft Torque']/v['Phase Current (peak)']
 speed_ratio=speed_rpm/v['Shaft Speed']
 base_iron=max(0,v['Total Losses (on load)']-v['Armature DC Copper Loss (on load)'])
 E0=v['Back EMF Line-Line Voltage (peak) (fundamental)']/math.sqrt(2)
 # Empirical harmonic allowance, valid only near this calibrated geometry family.
 fundamental0=math.hypot(E0+v['Phase Resistance']*v['Phase Current (rms)'],2*math.pi*v['Fundamental Frequency']*v['Q Axis Inductance']*.001*v['Phase Current (rms)'])
 crest=max(math.sqrt(2),v['Line-Line Terminal Voltage (peak)']/fundamental0)
 R0=v['Phase Resistance'];X0=2*math.pi*v['Fundamental Frequency']*v['Q Axis Inductance']*.001
 fill0=v['Copper Slot Fill (Slot Area)']
 bounds=list(search_bounds or [(55,100),(20,65),(1,8),(0.8,2.2)])
 # Legacy callers retain the original four-variable model. New UI jobs explicitly
 # supply the gap interval; this adds ONE dimension, never an angle grid.
 with_gap=airgap_bounds_mm is not None
 gap_range=airgap_bounds({'airgap_bounds_mm':airgap_bounds_mm}) if with_gap else None
 if with_gap:bounds.append(gap_range)
 g0=pilot.get('geometry_mm',{}).get('Airgap',mm(D0/130))
 tm0=pilot.get('geometry_mm',{}).get('Magnet_Thickness',mm(4*D0/130))
 ld0=v.get('D Axis Inductance',v['Q Axis Inductance'])*.001
 lq0=v['Q Axis Inductance']*.001
 phase0=v['Phase Current (peak)'];angle0=math.radians(pilot.get('readback',{}).get('PhaseAdvance',0))
 psi0=E0*math.sqrt(2)/(2*math.pi*v['Fundamental Frequency'])
 tbase=1.5*2*(psi0*phase0*math.cos(angle0)+(ld0-lq0)*(-phase0*math.sin(angle0))*phase0*math.cos(angle0))
 torque_factor=v['Shaft Torque']/tbase if tbase>0 else 1.
 def compute_prediction(x):
  D,L,N,W=x[:4];N=int(round(N));dl=D/D0*L/L0;vol=(D/D0)**2*(L/L0)
  K=kt*dl*N/N0;ip=torque_target*TORQUE_MATCH_TARGET_FACTOR/K;ir=ip/math.sqrt(2)
  r=R0*(N/N0)*(2*L+107.635*D/130)/(2*L0+107.635*D0/130)*(W0/W)**2
  e=E0*dl*N/N0*speed_ratio;xq=X0*(N/N0)**2*(L/L0)*speed_ratio
  copper=3*ir*ir*r;iron=base_iron*vol*speed_ratio**1.5
  loss=copper+iron;eff=power_required/(power_required+loss)*100
  terminal=math.hypot(e+r*ir,xq*ir)
  fill=fill0*(N/N0)*(W/W0)**2/(D/D0)**2
  slot_opening=mm(3*D/130);volume=math.pi/4*D*D*L
  control=None;gap=float(x[4]) if with_gap else mm(D/130)
  if with_gap or current_control!='ID0' or field_weakening:
   # Local PM load-line proxy (assumed recoil mu=1.05). FEA must check flux,
   # inductance and ranking; this is not a saturated geometry model.
   tm=mm(4*D/130);mu=1.05
   flux_gap=(tm/(tm+mu*gap))/(tm0/(tm0+mu*g0))
   psi=psi0*dl*N/N0*flux_gap
   l_scale=(N/N0)**2*(L/L0)*(g0+tm0/mu)/(gap+tm/mu)
   max_i=current_density_max_A_mm2*math.pi*W*W/4*math.sqrt(2) if current_density_max_A_mm2 is not None and current_density_max_A_mm2>0 else None
   control=solve_control(torque_Nm=torque_target*TORQUE_MATCH_TARGET_FACTOR,speed_rpm=speed_rpm,pole_pairs=2,
      psi_Wb=psi,ld_H=ld0*l_scale,lq_H=lq0*l_scale,resistance_ohm=r,
      voltage_peak_V=dc_voltage*VOLTAGE_RESERVE_FACTOR,current_peak_max_A=max_i,torque_factor=torque_factor,
      policy=current_control,field_weakening=field_weakening)
   ip=control['phase_peak_A'];ir=ip/math.sqrt(2);e=2*math.pi*speed_rpm/60*2*psi/math.sqrt(2)
   terminal=control['voltage_phase_peak_V']/math.sqrt(2);copper=3*ir*ir*r
   loss=copper+iron;eff=power_required/(power_required+loss)*100
  result=dict(diameter_mm=mm(D),length_mm=mm(L),turns_per_coil=N,wire_diameter_mm=mm(W),phase_peak_A=ip,line_peak_A=ip*math.sqrt(3),resistance_ohm=r,back_emf_phase_rms_V=e,terminal_line_rms_V=terminal,estimated_terminal_peak_V=terminal*(math.sqrt(2) if control else crest),efficiency_pct=eff,copper_loss_W=copper,other_loss_W=iron,fill=fill,volume_mm3=volume,wire_fits=wire_outer(W)<=slot_opening)
  result.update(estimated_shaft_torque_Nm=torque_target,estimated_dc_current_A=(power_required+loss)/dc_voltage,
                estimated_current_density_A_mm2=ir/(math.pi*W*W/4),
                dc_current_basis='Average DC current from motor input power; ideal inverter efficiency 100 percent; no switching/device losses',
                efficiency_requirement_state='not_requested' if efficiency_target is None else 'predicted_met' if eff>=efficiency_target else 'predicted_unmet')
  if with_gap:result['airgap_mm']=gap
  if control:result['operating_control']=control
  return result
 prediction_cache={};prediction_requests=0
 def predict(x):
  nonlocal prediction_requests
  prediction_requests+=1;key=tuple(x)
  if key not in prediction_cache:prediction_cache[key]=compute_prediction(x)
  return prediction_cache[key]
 evalcount=0;unique_evaluations=set()
 def score(x,objective):
  nonlocal evalcount
  unique_evaluations.add(tuple(x))
  evalcount+=1;p=predict(x)
  # Lexicographic ranking: physical screens first, then requirement shortfall.
  hard=max(0,p['estimated_terminal_peak_V']/(dc_voltage*VOLTAGE_RESERVE_FACTOR)-1)+max(0,p['terminal_line_rms_V']/(dc_voltage/math.sqrt(2)*VOLTAGE_RESERVE_FACTOR)-1)+max(0,p['fill']/.50-1)+max(0,wire_outer(x[3])/mm(3*x[0]/130)-1)
  if p.get('operating_control',{}).get('current_passed') is False:hard+=1
  if current_density_max_A_mm2 is not None:hard+=max(0,p['estimated_current_density_A_mm2']-current_density_max_A_mm2)/max(1.,current_density_max_A_mm2)
  gap=0. if efficiency_target is None else max(0,efficiency_target-p['efficiency_pct'])
  if dc_current_max_A is not None:gap+=100*max(0,p['estimated_dc_current_A']-dc_current_max_A)/max(1.,dc_current_max_A)
  size=p['volume_mm3']/150000;loss=(p['copper_loss_W']+p['other_loss_W'])/20
  value={'compact':size,'balanced':.5*size+.5*loss,'efficient':loss}[objective]
  return (hard>0,hard,gap>0,gap,value)
 results=[]
 ticks=grid_bounds(bounds)
 def decode(z):return [float(value)/10 if i!=2 else int(value) for i,value in enumerate(z)]
 for objective in ['compact','balanced','efficient']:
  # Non-overlapping scalar bands preserve feasibility / goal / secondary priority.
  def objective_value(z):
   physical,hard,unmet,gap,value=score(decode(z),objective)
   secondary=value/(1+value)
   if physical:return 3+hard/(1+hard)+1e-5*secondary
   if unmet:return 1+gap/(100+gap)+1e-5*secondary
   return secondary
  solved=differential_evolution(objective_value,ticks,integrality=[True]*len(ticks),popsize=8,maxiter=100,
       rng=20261021,polish=False,workers=1,tol=1e-7,atol=0)
  winner=decode(solved.x);p=dict(predict(winner));p['objective']=objective;p['score']=score(winner,objective);p['physical_screen_pass']=not p['score'][0]
  p['predicted_evaluated_constraints_met']=p['physical_screen_pass'] and not p['score'][2]
  p['target_met']=False  # Compatibility field: never claim all requirements verified from a local proxy.
  p['efficiency_shortfall_percentage_points']=None if efficiency_target is None else max(0,efficiency_target-p['efficiency_pct'])
  p['dc_current_shortfall_A']=None if dc_current_max_A is None else max(0,p['estimated_dc_current_A']-dc_current_max_A)
  p['dc_current_requirement_state']='not_requested' if dc_current_max_A is None else 'predicted_met' if p['dc_current_shortfall_A']==0 else 'predicted_unmet'
  results.append(p)
 status='predicted_evaluated_constraints_met' if any(p['predicted_evaluated_constraints_met'] for p in results) else ('best_effort_prediction' if any(p['physical_screen_pass'] for p in results) else 'no_physically_screened_candidate')
 data=dict(status=status,efficiency_target_pct=efficiency_target,dc_voltage_V=dc_voltage,torque_target_Nm=torque_target,speed_rpm=speed_rpm,estimated_crest_factor=crest,validation_status='not_FEA_validated',fallback_policy='Physical screens remain mandatory; minimize efficiency shortfall at fixed torque/speed before secondary objectives. Best found within bounds/budget, not a proven global maximum.',method='SciPy differential_evolution, integer 0.1 mm ticks, popsize=8, maxiter=100, 3 objectives; locally FEA-calibrated scaling surrogate; no global optimum guarantee',dimension_resolution_mm=.1,calibration=calibration_file,bounds=bounds,evaluations=evalcount,optimization_compute_s=time.perf_counter()-t,predictions=results)
 eligible=[p for p in results if p['physical_screen_pass']]
 data['best_available_prediction']=max(eligible,key=lambda p:p['efficiency_pct']) if eligible else None
 data['controller_limits']=controller
 data['unique_dimension_combinations_evaluated']=len(unique_evaluations)
 data['prediction_computations']=len(prediction_cache)
 data['prediction_cache_hits']=prediction_requests-len(prediction_cache)
 data['dc_current_max_A']=dc_current_max_A
 data['evaluation_policy']=evaluation_policy_snapshot()
 data['target_met_definition']='False until all required evidence is available; use predicted_evaluated_constraints_met for the evaluated subset only.'
 data['full_dimension_grid_combinations']=math.prod(hi-lo+1 for lo,hi in ticks)
 data['design_variable_count']=len(ticks)
 data['operating_policy']={'current_control':current_control,'field_weakening':field_weakening,'angle_grid_swept':False}
 if with_gap:
  data['effective_airgap_bounds_mm']=gap_range
  data['method']='SciPy differential_evolution on five integer dimension ticks; bounded analytical dq control (no angle sweep); local gap/flux/inductance proxy requires FEA validation'
  data['gap_model_assumption']='PM magnetic load-line proxy, recoil relative permeability assumed 1.05; no B/ripple/demagnetization prediction'
 if record_evaluated_points:data['evaluated_dimension_points']=sorted(unique_evaluations)
 data['diagnostic_candidates_only']=not bool(eligible)
 write_json(out/f'optimization{suffix}.json',data);print(json.dumps(data,ensure_ascii=False,indent=2));return data
if __name__=='__main__':optimize()

