"""One authorized Parallel/Parallel reference solve, paired to saved Radial data."""
from pathlib import Path
import contextlib
import json
import time
import traceback
import low_voltage as solver
from design_job import write_json

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'calibrations/surface_parallel_20261022'
REFERENCE=ROOT/'jobs/20261022_132138/calibration.json'


def run():
    import msvcrt
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'calibration.json').exists():
        print('Reference already saved; no additional Motor-CAD solve.',flush=True);return
    if (OUT/'solve_attempt.json').exists():raise RuntimeError('One reference attempt already recorded; automatic rerun is disabled')
    pilot=json.loads(REFERENCE.read_text(encoding='utf-8'))
    lock=(ROOT/'motorcad_execution.lock').open('a+b');mc=None;start=time.perf_counter()
    def progress(stage,**extra):
        write_json(OUT/'progress.json',{'stage':stage,'elapsed_s':time.perf_counter()-start,**extra})
        print(stage,flush=True)
    try:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        solver.OUT=OUT;progress('starting');mc,launch=solver.start()
        progress('preparing_materials');solver.prepare(mc)
        d=pilot['design'];options={**pilot['input_options'],'shape':'Parallel','magnetisation':'Parallel','phase_advance_deg':0.}
        geometry=pilot['geometry_mm']
        write_json(OUT/'solve_attempt.json',{'authorized_max_solves':1,'reference_source':str(REFERENCE),
            'design':d,'options':options,'geometry_mm':geometry})
        progress('reference_solve')
        result=solver.solve(mc,'calibration',d['diameter_mm'],d['length_mm'],d['turns_per_coil'],d['wire_diameter_mm'],
            d['input_peak_current_A'],d['voltage_V'],60,options=options,geometry=geometry)
        if result['readback']['BPMRotor']!=1 or result['readback']['Magnetization']!=0:raise RuntimeError('Parallel shape/direction readback failed')
        for key,value in geometry.items():
            if abs(result['geometry_mm'][key]-value)>1e-6:raise RuntimeError('Paired reference dimension changed: '+key)
        write_json(OUT/'reference_summary.json',{'source_radial':str(REFERENCE),'new_fea_solves':1,'launch_s':launch,
            'wall_s':time.perf_counter()-start,'solver_s':result['timings']['solver_s'],
            'shape':'Parallel','magnetisation':'Parallel','paired_geometry_passed':True})
        progress('completed',solver_s=result['timings']['solver_s'])
    except BaseException as exc:
        write_json(OUT/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('failed',error=str(exc));raise
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        lock.close()


if __name__=='__main__':run()
