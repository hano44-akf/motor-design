from pathlib import Path
import json,traceback
from ansys.motorcad.core import MotorCAD
out=Path(__file__).parent.resolve();out.mkdir(exist_ok=True)
mc=None; report={}
try:
 print('Starting isolated instance',flush=True)
 mc=MotorCAD(open_new_instance=True,keep_instance_open=False)
 mc.set_variable('MessageDisplayState',2)
 mc.set_visible(False)
 mc.load_from_file('C:/Program Files/ANSYS Inc/v261/motorcad/Tutorials/Electromagnetic_Model.mot')
 mc.save_to_file(str(out/'baseline.mot'))
 for k in ['Motor_Type','Stator_Lam_Dia','Stator_Lam_Length','Rotor_Lam_Length','Slot_Number','Pole_Number','Magnet_Thickness','Airgap','ArmatureTurns','PeakCurrent','ShaftSpeed','PhaseAdvance','MagnetTemperature','WindingTemperature','StatorLaminationTemperature','RotorLaminationTemperature','Magnet_Br','Magnet_MuR','Magnet_Arc_[ED]','MagWindingType','WindingConnection','DCBusVoltage']:
  try: report[k]=mc.get_variable(k)
  except Exception as e: report[k]=str(e)
 print(json.dumps(report,indent=2),flush=True)
except Exception: report['error']=traceback.format_exc();print(report['error'],flush=True)
finally:
 (out/'probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 if mc: mc.quit()
