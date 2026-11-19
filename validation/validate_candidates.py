from acceptance import assess
from low_voltage import *
mc=None;began=time.perf_counter();history=[];results=[]
opt=json.loads((OUT/'optimization.json').read_text(encoding='utf-8'))
try:
 mc,launch=start()
 for idx,pred in enumerate(opt['predictions']):
  name='ABC'[idx];D=round(pred['diameter_mm'],1);L=round(pred['length_mm'],1);N=pred['turns_per_coil'];W=math.floor(min(pred['wire_diameter_mm'],3*D/130-.12)*100)/100
  current=pred['line_peak_A'];last=None
  for iteration in range(4):
   last=solve(mc,f'{name}_tune{iteration}',D,L,N,W,current,9);history.append(last['label'])
   torque=last['values']['Shaft Torque']
   if .5<=torque<=.505:break
   if torque<=0:raise RuntimeError('Nonpositive torque')
   current*=.502/torque
  assessment=assess(last, efficiency_target=opt.get('efficiency_target_pct',88));passed=assessment['passed']
  results.append(dict(model=name,prediction=pred,design=last['design'],at_9V=last['label'],passes_9V=passed,assessment=assessment))
  (OUT/'candidate_validation.json').write_text(json.dumps(dict(status='running',history=history,results=results,launch_s=launch,wall_s=time.perf_counter()-began),ensure_ascii=False,indent=2),encoding='utf-8')
  print('CANDIDATE '+name+' PASS='+str(passed),flush=True)
 (OUT/'candidate_validation.json').write_text(json.dumps(dict(status='complete_9V',efficiency_target_pct=opt.get('efficiency_target_pct',88),history=history,results=results,launch_s=launch,wall_s=time.perf_counter()-began),ensure_ascii=False,indent=2),encoding='utf-8')
except Exception:
 print(traceback.format_exc(),flush=True)
 (OUT/'candidate_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
 if mc:mc.quit()
