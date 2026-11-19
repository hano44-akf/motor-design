"""Optimize three objectives per calibrated surface shape; no FEA calls."""
from pathlib import Path
import copy
import json
import time
from design_job import write_json
from formula_job import run_formula

ROOT=Path(__file__).resolve().parent
OUT=ROOT.parent/'outputs/surface_shape_comparison_20261022'


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    request=json.loads((ROOT/'jobs/20261022_162610/request.json').read_text(encoding='utf-8'))
    request['open_motorcad_after']=False
    results=[]
    for shape in ('Radial','Parallel'):
        req=copy.deepcopy(request);req['spm']={'shape':shape,'magnetisation':shape}
        if 'ui_input_snapshot' in req:req['ui_input_snapshot']['spm']=req['spm']
        job=time.strftime('%Y%m%d_%H%M%S');folder=ROOT/'jobs'/job
        if folder.exists():folder=folder.with_name(job+'_'+str(time.time_ns()%1000000))
        result=run_formula(req,folder)
        results.append({'shape':shape,'magnetisation':shape,'job':folder.name,'result':result})
    rows=[]
    for item in results:
        for c in item['result']['results']:
            rows.append({'shape':item['shape'],'magnetisation':item['magnetisation'],'objective':c['objective'],'id':c['id'],
                'stator_od_mm':c['design']['diameter_mm'],'stack_mm':c['design']['length_mm'],
                'efficiency_predicted_pct':c['prediction']['efficiency_pct'],
                'airgap_mm':c['design']['airgap_mm'],'turns':c['design']['turns_per_coil'],
                'wire_diameter_mm':c['design']['wire_diameter_mm'],'phase_advance_deg':c['design']['phase_advance_deg'],
                'physical_screen_pass':c['physical_screens_pass'],'validated':False,'job':item['job']})
    summary={'scope':'Shape-specific calibrated formula predictions; no candidate FEA',
        'request_conditions':request,'rows':rows,'runs':results,
        'new_reference_FEA_count_this_task':1,'new_candidate_FEA_count':0}
    write_json(OUT/'comparison.json',summary)
    import csv
    with (OUT/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({'rows':rows,'timings':[{'shape':r['shape'],'optimization_s':r['result']['timings']['optimization_compute_s'],
        'statistics':r['result']['search_statistics']} for r in results]},indent=2),flush=True)
    return summary


if __name__=='__main__':run()
