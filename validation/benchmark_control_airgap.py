"""Compare formula optimization only, reusing one saved FEA calibration.

No Motor-CAD startup, FEA, application opening, or automatic representative tuning.
"""
from pathlib import Path
import contextlib
import hashlib
import io
import json
import platform
import shutil
import statistics
import time
import numpy
import scipy
import optimize_low_voltage as engine

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'outputs/control_airgap_comparison_20261022'
SOURCE=ROOT/'validation/jobs/20261022_132138/calibration.json'


def run(repeats=3):
    OUT.mkdir(exist_ok=True)
    shutil.copyfile(SOURCE,OUT/'calibration_saved.json')
    cases=[('legacy_id0',{}),
           ('gap_id0',{'airgap_bounds_mm':[.4,.6]}),
           ('gap_mtpa',{'airgap_bounds_mm':[.4,.6],'current_control':'MTPA'}),
           ('gap_id0_fw',{'airgap_bounds_mm':[.4,.6],'field_weakening':True}),
           ('gap_mtpa_fw',{'airgap_bounds_mm':[.4,.6],'current_control':'MTPA','field_weakening':True})]
    samples={name:[] for name,_ in cases}
    original_control=engine.solve_control
    try:
        # Interleave case order to avoid attributing one-time warm-up to a feature.
        for repeat in range(repeats):
            for name,options in (cases if repeat%2==0 else list(reversed(cases))):
                counts={'dq_solves':0,'dq_scalar_evaluations':0}
                def counted(**kwargs):
                    response=original_control(**kwargs)
                    counts['dq_solves']+=1;counts['dq_scalar_evaluations']+=response['model_evaluations']
                    return response
                engine.solve_control=counted
                start=time.perf_counter()
                with contextlib.redirect_stdout(io.StringIO()):
                    result=engine.optimize(calibration_file='calibration_saved.json',suffix=f'_{name}_{repeat}',
                        output_dir=OUT,efficiency_target=88,dc_voltage=9,torque_target=.5,speed_rpm=3500,
                        search_bounds=[[55,100],[20,65],[1,8],[.8,2.2]],record_evaluated_points=True,**options)
                wall=time.perf_counter()-start
                row={'wall_s':wall,'engine_compute_s':result['optimization_compute_s'],
                     'evaluations':result['evaluations'],'unique_design_points':result['unique_dimension_combinations_evaluated'],
                     'full_grid_combinations':result['full_dimension_grid_combinations'],
                     'design_dimensions':result['design_variable_count'],**counts}
                samples[name].append(row)
                print(json.dumps({'case':name,'repeat':repeat,**row}),flush=True)
    finally:engine.solve_control=original_control
    comparison=[]
    for name,options in cases:
        rows=samples[name]
        assert len({r['evaluations'] for r in rows})==1
        comparison.append({'case':name,'options':options,'median_wall_s':statistics.median(r['wall_s'] for r in rows),
            'min_wall_s':min(r['wall_s'] for r in rows),'max_wall_s':max(r['wall_s'] for r in rows),
            **{key:rows[0][key] for key in rows[0] if key not in ('wall_s','engine_compute_s')},'repeats':rows})
    base=comparison[0]['median_wall_s']
    for item in comparison:
        item['time_ratio_to_legacy']=item['median_wall_s']/base
        item['extra_median_seconds']=item['median_wall_s']-base
        item['unique_evaluation_fraction_pct']=item['unique_design_points']/item['full_grid_combinations']*100
    payload={'scope':'Formula optimization only; 0 new Motor-CAD starts/solves/opens; same saved calibration',
        'optimizer':'SciPy differential_evolution; same seed/popsize factor/maxiter; 3 representative objectives',
        'settings':{'seed':20261021,'popsize_factor':8,'maxiter':100,'repeats':repeats,
                    'torque_Nm':.5,'rpm':3500,'voltage_V':9,'efficiency_min_pct':88},
        'environment':{'python':platform.python_version(),'numpy':numpy.__version__,'scipy':scipy.__version__},
        'calibration_source':str(SOURCE),'calibration_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        'comparison':comparison,
        'limitations':['Different formula models/airgaps mean timing comparison is not a proof of equal FEA accuracy.',
            'New gap flux/inductance proxy and constant-parameter dq need FEA validation.',
            'Ripple/B/thermal/demagnetization/PWM not calculated by this benchmark.',
            'This is the current DE engine with new options, not the proposed v0.2 Bayesian optimizer.',
            'One optimizer call per repeat; historical 7963 count came from two calls with different calibration feedback.']}
    (OUT/'comparison.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    return payload


if __name__=='__main__':run()
