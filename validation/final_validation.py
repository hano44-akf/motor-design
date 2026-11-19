from acceptance import assess
from low_voltage import *
mc=None;began=time.perf_counter();runs=[]
data=json.loads((OUT/'candidate_validation.json').read_text(encoding='utf-8'))
try:
 mc,launch=start()
 for candidate in data['results']:
  d=candidate['design'];name=candidate['model']
  for voltage in [9,12,16]:
   r=solve(mc,f'{name}_final_{voltage}V',d['diameter_mm'],d['length_mm'],d['turns_per_coil'],d['wire_diameter_mm'],d['input_peak_current_A'],voltage,120)
   assessment=assess(r, efficiency_target=data.get('efficiency_target_pct',88));ok=assessment['passed']
   runs.append(dict(model=name,voltage_V=voltage,label=r['label'],passed=ok,assessment=assessment,solver_s=r['timings']['solver_s']))
   (OUT/'final_validation.json').write_text(json.dumps(dict(status='running',runs=runs,launch_s=launch,wall_s=time.perf_counter()-began),ensure_ascii=False,indent=2),encoding='utf-8')
 (OUT/'final_validation.json').write_text(json.dumps(dict(status='completed',runs=runs,launch_s=launch,wall_s=time.perf_counter()-began),ensure_ascii=False,indent=2),encoding='utf-8')
except Exception:
 print(traceback.format_exc(),flush=True)
 (OUT/'final_error.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
 if mc:mc.quit()
