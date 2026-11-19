"""Stage 1: formula-only optimization using a compatible saved calibration."""
from pathlib import Path
import argparse
import contextlib
import hashlib
import io
import json
import time
import traceback
from study_io import write_json,export_job
from model_capabilities import validate_for_model,check_model_support
from request_schema import domain_snapshot,normalize_request
from optimize_low_voltage import optimize
from operating_control import control_policy,airgap_bounds
from formula_assessment import assess_prediction
from evaluation_policy import snapshot as evaluation_policy_snapshot
from rotor_catalog import ROOT as PROJECT_ROOT,catalog,resolve_rotor,reference_model,require_execution

ROOT=Path(__file__).resolve().parent
_REFERENCES={m['id']:m for m in catalog()['reference_models']}
CALIBRATION=PROJECT_ROOT/_REFERENCES['radial']['relative_path']
PARALLEL_CALIBRATION=PROJECT_ROOT/_REFERENCES['parallel']['relative_path']


def calibration_path(request):
    request=normalize_request(request)
    model=reference_model(request['spm'])
    if model is None:raise ValueError('Matching rotor/direction reference and performance model are not connected')
    # Compatibility aliases retained for existing test/maintenance callers;
    # rotor/reference discovery itself is now catalog-driven.
    path={'radial':CALIBRATION,'parallel':PARALLEL_CALIBRATION}.get(model['id'],PROJECT_ROOT/model['relative_path'])
    if not path.is_file():raise ValueError('Matching saved FEA calibration is not available: '+str(path))
    reference=json.loads(path.read_text(encoding='utf-8'))
    options=reference.get('input_options',{})
    if resolve_rotor(options)['id']!=resolve_rotor(request['spm'])['id'] or options.get('magnetisation')!=request['spm'].get('magnetisation'):
        raise ValueError('Calibration shape/direction mismatch')
    if options.get('temperature_C')!=request['temperatures_C'][0]:raise ValueError('Calibration reference temperature mismatch')
    if reference['component_materials'].get('Magnet')!=request['magnet'] or reference['component_materials'].get('Stator Lam (Back Iron)')!=request['core']:
        raise ValueError('Calibration material mismatch')
    return path


def validate_formula(request):
    request=validate_for_model(request,'formula')
    if request['temperatures_C'][0]!=20:
        raise ValueError('Saved formula calibration is at 20 C; use 20 C as the reference. Additional min/max temperatures are checked in the later FEA stage.')
    calibration_path(request)
    require_execution(request,'formula')
    return request


def run_formula(request,folder):
    request=validate_formula(request);folder=Path(folder).resolve();folder.mkdir(exist_ok=True,parents=True)
    write_json(folder/'request.json',request)
    write_json(folder/'domain_request.json',domain_snapshot(request))
    write_json(folder/'model_support.json',check_model_support(request,'formula'))
    start=time.perf_counter();op=request['operating_point'];policy=control_policy(request)
    write_json(folder/'progress.json',{'status':'optimizing','started_unix':time.time(),'elapsed_s':0,'solves_this_session':0})
    try:
        source=calibration_path(request)
        calibration=json.loads(source.read_text(encoding='utf-8'))
        write_json(folder/'calibration_saved.json',calibration)
        with contextlib.redirect_stdout(io.StringIO()):
            output=optimize(calibration_file='calibration_saved.json',output_dir=folder,
                efficiency_target=op.get('efficiency_min_pct'),dc_voltage=min(op['voltages_V']),
                torque_target=op['torque_Nm'],speed_rpm=op['speed_rpm'],search_bounds=request['bounds'],
                switching_frequency_hz=request.get('switching_frequency_hz'),airgap_bounds_mm=airgap_bounds(request),
                current_control=policy['current_control'],field_weakening=policy['field_weakening'],
                current_density_max_A_mm2=op.get('current_density_max_A_mm2'),dc_current_max_A=op.get('dc_current_max_A'))
        models=[];seen=set()
        for pred in output['predictions']:
            signature=tuple(pred[k] for k in ('diameter_mm','length_mm','turns_per_coil','wire_diameter_mm','airgap_mm'))
            if signature in seen:continue
            seen.add(signature)
            control=pred.get('operating_control',{})
            design={k:pred[k] for k in ('diameter_mm','length_mm','turns_per_coil','wire_diameter_mm','airgap_mm')}
            design.update(input_peak_current_A=pred['line_peak_A'],geometry_mm={'Airgap':pred['airgap_mm']},
                          phase_advance_deg=control.get('phase_advance_deg',0.),control_prediction=control)
            models.append({'id':chr(65+len(models)),'objective':pred['objective'],'design':design,'prediction':pred,
                           'runs':[],'target_met':False,'physical_screens_pass':pred['physical_screen_pass'],
                           'status':'formula_prediction_only','formula_review':assess_prediction(pred,request),
                           'verification_complete':False})
        elapsed=time.perf_counter()-start
        fixed=sum(abs(hi-lo)<1e-9 for lo,hi in output['bounds'])
        result={'schema':'spm-formula-result-v1','stage':'formula','status':'formula_prediction_only',
                'request':request,'results':models,'best_available':None,'operating_policy':policy,
                'rotor_configuration':require_execution(request,'formula'),
                'effective_airgap_bounds_mm':airgap_bounds(request),
                'search_statistics':{'design_dimensions':output['design_variable_count'],
                    'free_design_dimensions':output['design_variable_count']-fixed,
                    'full_grid_combinations':output['full_dimension_grid_combinations'],
                    'objective_evaluations':output['evaluations'],'unique_design_points':output['unique_dimension_combinations_evaluated'],
                    'prediction_computations':output.get('prediction_computations'),
                    'prediction_cache_hits':output.get('prediction_cache_hits'),
                    'angle_grid_swept':False,'motorcad_solves':0},
                'timings':{'optimization_compute_s':output['optimization_compute_s'],'session_wall_s':elapsed,
                    'final_solver_sum_s':0.,'all_recorded_solver_s':0.,'recorded_solve_count':0},
                'calibration':{'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                    'shape':request['spm']['shape'],'magnetisation':request['spm']['magnetisation'],
                    'temperature_C':20,'scope':'Reused saved FEA; no new Motor-CAD execution'},
                'model_validity':check_model_support(request,'formula')['model_validity'],
                'evaluation_policy':evaluation_policy_snapshot(),
                'limitations':['Formula prediction only; B, ripple, PWM, demagnetization and nonlinear control optimality remain unverified.',
                    'Local scaling/gap model may be inaccurate outside its reference geometry; this is not an implemented Bayesian optimization engine.']}
        write_json(folder/'result.json',result);export_job(folder,result)
        write_json(folder/'progress.json',{'status':'completed','stage':'formula','elapsed_s':elapsed,'solves_this_session':0,'models':len(models)})
        return result
    except Exception as exc:
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()})
        write_json(folder/'progress.json',{'status':'failed','error':str(exc),'elapsed_s':time.perf_counter()-start})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--job',type=Path,required=True);args=parser.parse_args()
    run_formula(json.loads((args.job/'request.json').read_text(encoding='utf-8')),args.job)
