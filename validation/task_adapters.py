"""Named task recipes. No arbitrary shell commands; native imports are lazy."""
import copy
import json
from pathlib import Path
import re
import time
from task_store import ROOT,NATIVE,project_file,file_digest


def prepare_spec(spec):
    spec=copy.deepcopy(spec);kind=spec.get('kind');payload=spec.get('payload',{})
    files=list(spec.get('input_files',[]))
    if not isinstance(payload,dict):raise ValueError('Task payload required')
    if kind=='formula':
        from formula_job import validate_formula,calibration_path
        validate_formula(payload['request']);files.append(str(calibration_path(payload['request'])))
    elif kind=='motorcad_verify':
        from model_capabilities import validate_for_model
        request=payload['request'];validate_for_model(request,'verification')
        source=request.get('formula_source_job','')
        if not re.fullmatch(r'\d{8}_\d{6}(?:_\d+)?',source):raise ValueError('Saved formula job required')
        path=project_file(ROOT/'validation/jobs'/source/'result.json');saved=json.loads(path.read_text(encoding='utf-8'))
        selected=request.get('selected_model_ids',[])
        if saved.get('stage')!='formula' or not isinstance(selected,list) or not selected or len(set(selected))!=len(selected) or not set(selected)<={m['id'] for m in saved['results']}:
            raise ValueError('Distinct saved candidate IDs required')
        # Keep source geometry/material/load requirements immutable; allowed
        # verification changes select saved candidates and operating conditions.
        original=saved['request']
        for field in ('core','magnet','spm','connection','strands','paths','bounds','airgap_bounds_mm','control'):
            if request.get(field)!=original.get(field):raise ValueError('Saved formula input mismatch: '+field)
        for field in ('torque_Nm','speed_rpm','current_control','field_weakening'):
            if request['operating_point'].get(field)!=original['operating_point'].get(field):raise ValueError('Saved load/control mismatch: '+field)
        if not set(request['operating_point']['voltages_V'])<=set(original['operating_point']['voltages_V']):raise ValueError('Select saved voltage conditions')
        if not set(request.get('temperatures_C',[20]))<=set(original.get('temperatures_C',[20])):raise ValueError('Select saved temperature conditions')
        files.append(str(path))
    elif kind in ('motorcad_diagnostic','motorcad_mesh'):
        path=project_file(payload.get('source',''));reference=json.loads(path.read_text(encoding='utf-8'))
        from model_capabilities import validate_for_model
        # Current diagnostic recipes are intentionally confined to saved paired
        # Surface 4p/12s references; generic native paths are not executable yet.
        options=reference.get('input_options',{});native=reference.get('readback',{})
        if options.get('shape') not in ('Radial','Parallel') or native.get('Pole_Number')!=4 or native.get('Slot_Number')!=12:
            raise ValueError('Diagnostic recipe requires a saved supported 4p/12s Surface reference')
        expected_direction={'Radial':'Radial','Parallel':'Parallel'}[options['shape']]
        mats=reference.get('component_materials',{})
        if options.get('magnetisation')!=expected_direction or options.get('connection')!='delta' or options.get('strands')!=1 or options.get('paths')!=1 or options.get('temperature_C')!=20:
            raise ValueError('Diagnostic control/winding conditions are outside the current recipe')
        if mats.get('Magnet')!='JL Mag Rare-Earth | N48UH' or any(mats.get(k)!='POSCO | 50PN470' for k in ('Stator Lam (Back Iron)','Stator Lam (Tooth)','Rotor Lam (Back Iron)')):
            raise ValueError('Diagnostic material reference is not supported')
        files.append(str(path))
    elif kind=='mock':
        duration=payload.get('duration_s',0)
        if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not 0<=duration<=30:raise ValueError('Mock duration 0..30 seconds required')
        fail=payload.get('fail_until_attempt',0)
        if isinstance(fail,bool) or not isinstance(fail,int) or not 0<=fail<=10:raise ValueError('Mock failure count 0..10 required')
    elif kind!='manual_check':raise ValueError('Unsupported task kind')
    if kind in NATIVE:
        files.append(str(project_file('validation/baseline.mot')))
    material=ROOT/'material_library/normalized_20261020/materials_si.sqlite'
    if kind!='mock' and material.is_file():files.append(str(material))
    spec['input_files']=sorted({str(project_file(p)) for p in files})
    return spec


def execute(kind,payload,folder,attempt):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    if kind=='mock':
        time.sleep(payload.get('duration_s',0))
        if attempt<=payload.get('fail_until_attempt',0):raise RuntimeError('Requested mock failure')
        result={'status':'mock_completed','value':payload.get('value'),'attempt':attempt,'motorcad_solves':0}
        from study_io import write_json
        write_json(folder/'result.json',result)
    elif kind=='formula':
        from formula_job import run_formula
        run_formula(payload['request'],folder)
    elif kind=='motorcad_verify':
        from verify_formula_job import run_verification
        run_verification(payload['request'],folder)
    elif kind=='motorcad_diagnostic':
        from background_validation import diagnostics
        diagnostics(project_file(payload['source']),folder)
    elif kind=='motorcad_mesh':
        from mesh_review import run_phase
        run_phase(project_file(payload['source']),folder)
    else:raise ValueError('Task has no executable recipe')
    result_path=folder/'result.json'
    if not result_path.is_file():raise RuntimeError('Task returned without a persisted result')
    result=json.loads(result_path.read_text(encoding='utf-8'))
    return {'result_file':str(result_path),'result_sha256':file_digest(result_path),
            'calculation_status':result.get('status'),'evaluation_passed':None,
            'scope':'Task completion is separate from motor requirement acceptance; inspect saved result.'}
