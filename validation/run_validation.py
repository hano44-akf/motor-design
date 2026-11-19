"""One isolated derivative SPM design; no edits to installed examples or user sessions."""
from pathlib import Path
import json,traceback,time
from ansys.motorcad.core import MotorCAD
OUT=Path(__file__).resolve().parent/'run_20261021';OUT.mkdir(exist_ok=True)
report={'status':'starting','source':'installed Electromagnetic_Model.mot copied as baseline','scenarios':[]}
def save(): (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
mc=None
try:
 mc=MotorCAD(open_new_instance=True,keep_instance_open=False);mc.set_variable('MessageDisplayState',2);mc.set_visible(False)
 mc.load_from_file(str(OUT.parent/'baseline.mot'))
 settings={'Stator_Lam_Length':75,'Rotor_Lam_Length':75,'Magnet_Length':75,'ShaftSpeed':1500,'CurrentDefinition':0,'PeakCurrent':5,'PhaseAdvance':0,'DCBusVoltage':300,'TorquePointsPerCycle':60,'TorqueNumberCycles':1,'BackEMFPointsPerCycle':60,'BackEMFNumberCycles':1,'BackEMFCalculation':True,'TorqueCalculation':True,'CoggingTorqueCalculation':False,'ElectromagneticForcesCalc_OC':False,'ElectromagneticForcesCalc_Load':False,'TorqueSpeedCalculation':False,'DemagnetizationCalc':False,'InductanceCalc':False,'BPMShortCircuitCalc':False}
 report['settings']={}
 for k,v in settings.items():
  mc.set_variable(k,v);report['settings'][k]=mc.get_variable(k)
 report['geometry']={k:mc.get_variable(k) for k in ['Stator_Lam_Dia','Stator_Bore','Airgap','Slot_Number','Pole_Number','Magnet_Thickness','Magnet_Arc_[ED]','MagTurnsConductor','ParallelPaths','WindingConnection']}
 for temp in [20,60,100]:
  scenario={'temperature_C':temp,'status':'running'};report['scenarios'].append(scenario)
  for k in ['Magnet_Temperature','StatorConductor_Temperature','StatorLam_Temperature','RotorLam_Temperature']:mc.set_variable(k,temp)
  model=OUT/f'validation_{temp}C.mot';mc.save_to_file(str(model));report['status']='solving';save();print(f'SOLVING {temp}C',flush=True)
  started=time.time();mc.do_magnetic_calculation();scenario['elapsed_seconds']=time.time()-started
  mc.export_results('EMagnetic',str(OUT/f'results_{temp}C.csv'))
  scenario['values']={};scenario['unavailable']={}
  for k in ['ShaftTorque','AvTorqueVW','ShaftPower','Efficiency','Loss_Total','ArmatureCopperLoss','CopperLoss','DCResistance','PhaseResistance','RMSCurrent','PeakCurrent','PeakLineLineVoltage','RMSLineLineVoltage','BackEMF','BEMF','Magnet_Br','Magnet_ur','Magnet_Br_at_20','MeanTurnLength','ConductorArea','MagTurnsConductor','MagnetFluxLinkage','Ld','Lq']:
   try:scenario['values'][k]=mc.get_variable(k)
   except Exception as e:scenario['unavailable'][k]=str(e)
  try:scenario['torque_graph']=mc.get_magnetic_graph('TorqueVW')
  except Exception as e:scenario['graph_error']=str(e)
  scenario['status']='solved';mc.save_to_file(str(model));save();print(f'DONE {temp}C '+json.dumps(scenario['values']),flush=True)
 report['status']='solved';save()
except Exception:
 report['status']='failed';report['error']=traceback.format_exc();save();print(report['error'],flush=True)
finally:
 if mc:
  try:mc.quit()
  except Exception:pass
