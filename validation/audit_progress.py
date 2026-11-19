from pathlib import Path
import json
from acceptance import assess

root=Path(__file__).resolve().parent/'optimization_12V_50PN470'
results={p.stem:assess(json.loads(p.read_text(encoding='utf-8'))) for p in sorted(root.glob('*_final_*V.json'))}
results['pilot_arc120']=assess(json.loads((root/'pilot_arc120.json').read_text(encoding='utf-8')))
original=json.loads((root/'final_validation.json').read_text(encoding='utf-8'))
audit={'audit_date_KST':'2026-10-22','raw_outputs_preserved':True,'note':'Old passed flags omitted the peak-voltage screen; use this audit for status.','results':results,'all_voltage_pass_models':[m for m in 'ABC' if all(results[f'{m}_final_{v}V']['passed'] for v in [9,12,16])],'final_solver_sum_s':sum(r['solver_s'] for r in original['runs']),'final_batch_wall_s':original['wall_s']}
(root/'progress_audit_20261022.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'all_voltage_pass_models':audit['all_voltage_pass_models'],'failures':{k:v['failures'] for k,v in results.items()},'final_solver_sum_s':audit['final_solver_sum_s'],'final_batch_wall_s':audit['final_batch_wall_s']},indent=2))
