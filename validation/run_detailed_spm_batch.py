"""Authorized, sequential native DOE worker. Pending Breadloaf FEA stays blocked.

Uses frozen plan.json in a fresh output directory. No automatic retries.
"""
import argparse
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import time
import traceback
from detailed_spm_recipe import apply_recipe_checked
from study_io import write_json

ROOT=Path(__file__).resolve().parent


def assert_values(mc, expected):
    import math
    actual={key:mc.get_variable(key) for key in expected}
    for key,value in expected.items():
        if not isinstance(actual[key],(int,float)) or not math.isfinite(actual[key]) or abs(actual[key]-value)>1e-6:
            raise RuntimeError('Native readback mismatch: '+key)
    return actual


def run(folder):
    import msvcrt
    import low_voltage as solver
    folder=Path(folder).resolve()
    if (folder/'progress.json').exists():raise ValueError('Fresh batch directory required; inspect previous results before retrying')
    plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    solver.OUT=folder
    mc=None;lock=None;rows=[];checks=[];started=time.time()
    blocked=[c['id'] for g in plan['groups'] for c in g['cases'] if not c['recipe']['ready_for_readback']]
    def progress(state,**extra):
        write_json(folder/'progress.json',{'status':state,'started_unix':started,'elapsed_s':time.time()-started,
            'planned_fea':plan['planned_fea'],'executable_fea':plan['planned_fea']-len(blocked),
            'completed_fea':len(rows),'blocked_fea':len(blocked),'blocked_case_ids':blocked,
            'mapping_checks_completed':len(checks),**extra})
    def stop_boundary():
        if (folder/'cancel.request').exists():raise InterruptedError('Stop requested; stopped between native calls')
    try:
        lock=(ROOT/'motorcad_execution.lock').open('a+b')
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        progress('starting')
        mc,launch=solver.start()
        materials=solver.prepare(mc)
        write_json(folder/'settings.json',{'launch_s':launch,'materials':materials,
            'operating_point':{'rpm':3500,'temperature_C':20,'bus_V':9,'input_line_peak_A':40,
                'turns_per_coil':6,'wire_diameter_mm':1.8,'connection':'delta','phase_advance_ed':0},
            'scope':'Fixed-current local DOE, not requested-torque optimization or inverter voltage feasibility proof.',
            'inductance':'Inductance analysis disabled; no new L validation is claimed.',
            'mesh':{'points_per_electrical_cycle':240,'cycles':2,'airgap_mesh':960,
                    'magnet_mesh_mm':.5,'lamination_mesh_mm':1},
            'code_hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                (Path(__file__),ROOT/'detailed_spm_recipe.py',ROOT/'low_voltage.py')}})
        for group in plan['groups']:
            stop_boundary();progress('mapping_check',active_shape=group['shape'])
            recipe=group['cases'][0]['recipe']
            mc.load_from_file(str(folder/'material_seed.mot'))
            if recipe['ready_for_readback']:
                apply_recipe_checked(mc,recipe)
                expected=recipe['native_variables']
            else:
                # Probe real names and persistence only. This is not permission
                # to bypass the production Breadloaf corner-geometry gate.
                expected=copy.deepcopy(recipe['native_variables'])
                expected.update({'MagnetReduction':group['cases'][0]['point']['magnet_reduction_mm'],
                                 'CircumferentialSegments':1})
                for key in ['BPMRotor']+[k for k in expected if k!='BPMRotor']:
                    mc.set_variable(key,expected[key])
                assert_values(mc,expected)
            model=folder/(group['shape'].lower()+'_mapping.mot')
            mc.save_to_file(str(model));mc.load_from_file(str(model))
            actual=assert_values(mc,expected)
            checks.append({'shape':group['shape'],'saved_model':str(model),'readback':actual,
                'input_persistence_verified':True,'full_geometry_qualified':False,
                'remaining_gate':recipe['native_mapping_pending']})
            write_json(folder/'mapping_checks.json',checks)
        for group in plan['groups']:
            for case in group['cases']:
                if case['id'] in blocked:continue
                stop_boundary();progress('solving',active_case=case['id'],role=case['role'])
                recipe=case['recipe'];native=recipe['native_variables']
                options=copy.deepcopy(recipe['resolved_request']['spm']);options.pop('parameters',None)
                options['magnet_arc_deg']=native['Magnet_Arc_[ED]']
                geometry={key:value for key,value in native.items() if key in
                    {'Housing_Dia','Stator_Lam_Dia','Stator_Bore','Shaft_Dia','Tooth_Width','Slot_Depth',
                     'Slot_Opening','Tooth_Tip_Depth','Magnet_Thickness','Airgap','Stator_Lam_Length',
                     'Rotor_Lam_Length','Magnet_Length','Shaft_Dia_[F]','Shaft_Dia_[R]'}}
                row=solver.solve(mc,case['id'],85,20,6,1.8,40,9,240,options=options,geometry=geometry,
                    calculation_settings={'AirgapMeshPoints_layers':960,'AirgapMeshPoints_mesh':960,
                        'MagnetMeshLength':.5,'StatorLamMeshLength':1,'RotorLamMeshLength':1,
                        'TorqueNumberCycles':2,'BackEMFNumberCycles':2},
                    graph_names=['TorqueVW','TorqueMsVw'])
                assert_values(mc,native)
                if row['component_materials']!=materials:raise RuntimeError('Material changed')
                row.update({'doe_role':case['role'],'doe_point':case['point'],
                    'performance_model_qualified':False,'native_recipe':recipe})
                write_json(folder/(case['id']+'.json'),row)
                rows.append({'id':case['id'],'shape':group['shape'],'role':case['role'],
                    'output':str(folder/(case['id']+'.json')),'timings':row['timings'],
                    'values':row['values'],'voltage_limit_exceeded':row['voltage_limit_exceeded']})
                write_json(folder/'partial_results.json',rows)
        write_json(folder/'result.json',{'status':'completed_with_blocked_cases' if blocked else 'completed',
            'runs':rows,'blocked_case_ids':blocked,'mapping_checks':checks,'elapsed_s':time.time()-started,
            'limitations':(['Breadloaf corner geometry remains pending; blocked cases were not executed.'] if blocked else [])+[
                'No torque retuning, thermal or stress analysis, inductance or demagnetization analysis.',
                'Model qualification and holdout analysis must follow this batch.']})
        progress('completed_with_blocked_cases' if blocked else 'completed')
    except BaseException as exc:
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()})
        progress('stopped' if isinstance(exc,InterruptedError) else 'failed',error=str(exc))
        raise
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        if lock:lock.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    run(parser.parse_args().output)
