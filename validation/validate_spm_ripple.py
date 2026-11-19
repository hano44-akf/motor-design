"""Native-boundary SPM prototype screening and independent FEA checks.

Experimental path for all four SPM types. Does NOT unlock production adapters.
Exports native geometry without FEA, locks predictions, then evaluates candidates.
"""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import time
import traceback
import numpy as np
from scipy.stats import qmc
from dimension_grid import mm,wire_outer
from geometry_adapters import build_geometry
from native_winding_review import review as winding_review
from spm_ripple import SPM_TYPES,predict,acceptance
from spm_ripple_calibration import fit as fit_calibration,apply as apply_calibration
from study_io import write_json
from magnet_boundary_check import check_region

ROOT=Path(__file__).resolve().parent


def candidates(count=16):
    if count!=16:raise ValueError('Frozen pilot uses 16 candidates per family')
    samples=qmc.Sobol(d=5,scramble=True,seed=20261103).random_base2(4)
    groups=[]
    for index,rotor in enumerate(SPM_TYPES):
        cases=[]
        for i,x in enumerate(samples):
            geometry=build_geometry({'shape':'Radial'},85,20)
            geometry.update(Tooth_Width=8.1,Slot_Depth=8.8,Slot_Opening=mm(2+x[0]),
                Magnet_Thickness=mm(1.2+1.8*x[1]),Airgap=mm(.4+.2*x[2]))
            native={**geometry,'BPMRotor':15 if index==3 else index,'Magnetization':0 if index in (1,3) else 1,
                'Pole_Number':4,'Slot_Number':12,'ShaftSpeed':3500,'PhaseAdvance':0,
                'WindingConnection':1,'NumberStrandsHand':1,'ParallelPaths':1,'Wire_Type_Stator':2,
                'MagTurnsConductor':6,'Copper_Diameter':1.8,'Wire_Diameter':wire_outer(1.8),
                'PeakCurrent':40,'CurrentDefinition':0,'DCBusVoltage':9,'CircumferentialSegments':1,
                'Magnet_Temperature':20,'StatorConductor_Temperature':20,'StatorLam_Temperature':20,'RotorLam_Temperature':20}
            native['Magnet_Arc_[ED]']=float(round(60+100*x[3],2))
            if index==2:native['MagnetReduction']=mm(min(.8,.4*geometry['Magnet_Thickness'])*x[4])
            cases.append({'id':rotor+'_'+str(i+1).zfill(2),'rotor_id':rotor,
                'magnetisation':'Parallel' if index in (1,3) else 'Radial',
                'geometry_mm':geometry,'expected_native':native})
        groups.append({'rotor_id':rotor,'cases':cases})
    return {'schema':'spm-ripple-native-pilot-v1','scope':list(SPM_TYPES),'groups':groups,
        'geometry_candidates':64,'selected_models_per_family':2,'maximum_fea_calls':8,
        'selection_rule':'Two lowest frozen valid proxy ripple predictions per family, before observing FEA.',
        'acceptance_rule':'Predicted<=20pct and independent FEA<=50pct; absence of a qualifying prediction is not a pass.',
        'saturation_scope':'Experimental linear model; actual saturation may invalidate prediction.',
        'production_optimizer_connected':False}


def checked(mc,settings):
    for key in ['BPMRotor']+[k for k in settings if k!='BPMRotor']:mc.set_variable(key,settings[key])
    actual={k:mc.get_variable(k) for k in settings}
    for k,v in settings.items():
        if not isinstance(actual[k],(int,float)) or not np.isfinite(actual[k]) or abs(actual[k]-v)>1e-6:
            raise RuntimeError('Input readback mismatch: '+k)
    return actual


def run(folder,calibration_source=None):
    import msvcrt
    import low_voltage as solver
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    if (folder/'progress.json').exists():raise ValueError('Fresh validation folder required')
    plan=candidates()
    plan['calibration_source']=str(Path(calibration_source).resolve()) if calibration_source else None
    plan['geometry_refresh']='reset_adaptive_geometry before extracting each native boundary'
    plan['flat_native_mapping_evidence']='outputs/spm_ripple_followup_20261103/type_probe_rebuilt/type_15.json; official Surface Flat geometry'
    write_json(folder/'plan.json',plan)
    solver.OUT=folder;mc=None;lock=None;started=time.time();exports=[];failures=[];runs=[]
    def progress(status,**extra):
        write_json(folder/'progress.json',{'status':status,'started_unix':started,'elapsed_s':time.time()-started,
            'geometry_candidates':64,'exported_candidates':len(exports),'geometry_failures':len(failures),
            'maximum_fea_calls':8,'completed_fea':len(runs),**extra})
    def stop():
        if (folder/'cancel.request').exists():raise InterruptedError('Stopped at native call boundary')
    try:
        lock=(ROOT/'motorcad_execution.lock').open('a+b')
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        progress('starting');mc,_=solver.start();materials=solver.prepare(mc)
        write_json(folder/'code_hashes.json',{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            for name in ('spm_ripple.py','validate_spm_ripple.py','low_voltage.py')})
        calibration=None;excluded=set()
        if calibration_source:
            source=Path(calibration_source).resolve();old=json.loads((source/'result.json').read_text(encoding='utf-8'))
            development=[];progress('calibration_geometry_refresh')
            for row in old['runs']:
                snapshot=json.loads((source/(row['id']+'_snapshot.json')).read_text(encoding='utf-8'))
                mc.load_from_file(str(source/(row['id']+'.mot')));checked(mc,snapshot['expected_native']);mc.reset_adaptive_geometry()
                if any(abs(mc.get_variable(k)-v)>1e-6 for k,v in snapshot['expected_native'].items()):raise ValueError('Calibration inputs changed during rebuild')
                tree=mc.get_geometry_tree()._to_json();magnets=[m for m in tree['regions'].values() if m.get('region_type')=='Magnet']
                if len(magnets)!=1:raise ValueError('Calibration geometry changed topology')
                snapshot['magnet_region']=magnets[0]
                graph=row['graphs']['TorqueMsVw'];x=graph['x'];y=graph['y']
                if len(y)!=481 or abs(x[-1]-x[0]-720)>1e-6:raise ValueError('Unsupported native angle cycle for calibration')
                raw=predict(snapshot,2880,480)
                development.append({'id':row['id'],'rotor_id':row['rotor_id'],'proxy':raw,'actual_waveform_Nm':y[:-1]})
                excluded.add(row['id'])
            calibration=fit_calibration(development);write_json(folder/'calibration.json',calibration)
            plan['excluded_calibration_ids']=sorted(excluded)
            plan['schema']='spm-ripple-native-pilot-v2'
            write_json(folder/'plan.json',plan)
            write_json(folder/'calibration_sources.json',{'source':str(source),'sha256':{r['id']:hashlib.sha256((source/(r['id']+'_validation.json')).read_bytes()).hexdigest() for r in old['runs']}})
        for group in plan['groups']:
            for case in group['cases']:
                stop();progress('geometry_and_proxy',active_case=case['id'])
                try:
                    mc.load_from_file(str(folder/'material_seed.mot'));actual=checked(mc,case['expected_native'])
                    model=folder/(case['id']+'.mot');mc.save_to_file(str(model));mc.load_from_file(str(model))
                    if any(abs(mc.get_variable(k)-v)>1e-6 for k,v in case['expected_native'].items()):raise ValueError('Save/reload changed inputs')
                    mc.reset_adaptive_geometry()
                    if any(abs(mc.get_variable(k)-v)>1e-6 for k,v in case['expected_native'].items()):raise ValueError('Candidate inputs changed during geometry rebuild')
                    tree=mc.get_geometry_tree();native_tree=tree._to_json()
                    write_json(folder/(case['id']+'_geometry.json'),native_tree)
                    magnets=[r for r in native_tree['regions'].values() if r.get('region_type')=='Magnet']
                    if len(magnets)!=1:raise ValueError('Prototype requires one defining magnet region with pole duplication')
                    magnet=magnets[0]
                    boundary_check=check_region(magnet)
                    if not boundary_check['passed']:raise ValueError('Magnet boundary self-intersection/open-boundary check failed')
                    if case['rotor_id']=='surface_flat' and any(e['type']!='line' for e in magnet['entities']):raise ValueError('Flat native boundary is not all straight edges')
                    winding=winding_review(model)
                    if not winding['balanced']:raise ValueError('Unbalanced native winding')
                    snapshot={**case,'poles':4,'slots':12,'connection':'delta','paths':1,'turns_per_coil':6,
                        'line_peak_A':40,'magnet_br_T':1.4,'magnet_mu_r':1.05,
                        'coils':winding['coils'],'magnet_region':magnet,'native_readback':actual}
                    proxy=predict(snapshot,2880,480)
                    if calibration:proxy=apply_calibration(proxy,calibration,allow_unseen_shape=True)
                    write_json(folder/(case['id']+'_snapshot.json'),snapshot)
                    write_json(folder/(case['id']+'_proxy.json'),proxy)
                    exports.append({'id':case['id'],'rotor_id':case['rotor_id'],'ripple_pct':proxy['ripple_pct'],
                        'mean_Nm':proxy['mean_Nm'],'snapshot':snapshot,'proxy':proxy})
                except Exception as exc:
                    failures.append({'id':case['id'],'stage':'geometry_proxy','error':str(exc),'traceback':traceback.format_exc()})
                    write_json(folder/'geometry_failures.json',failures)
                write_json(folder/'proxy_summary.json',[{k:v for k,v in e.items() if k not in ('snapshot','proxy')} for e in exports])
        selected=[]
        for rotor in SPM_TYPES:
            valid=[e for e in exports if e['rotor_id']==rotor and e['ripple_pct'] is not None and e['mean_Nm']>0 and e['id'] not in excluded]
            selected.extend(sorted(valid,key=lambda e:e['ripple_pct'])[:2])
        # Freeze IDs and predictions before any FEA; never calibrate on these
        # held-out native results and then claim the same validation as fresh.
        write_json(folder/'frozen_selection.json',[{'id':e['id'],'rotor_id':e['rotor_id'],
            'predicted_ripple_pct':e['ripple_pct'],'prediction_sha256':hashlib.sha256((folder/(e['id']+'_proxy.json')).read_bytes()).hexdigest()} for e in selected])
        for e in selected:
            stop();progress('fea_validation',active_case=e['id'],planned_fea=len(selected))
            case=e['snapshot'];mc.load_from_file(str(folder/(e['id']+'.mot')))
            checked(mc,case['expected_native'])
            settings={'TorquePointsPerCycle':240,'TorqueNumberCycles':2,'BackEMFPointsPerCycle':240,'BackEMFNumberCycles':2,
                'AirgapMeshPoints_layers':960,'AirgapMeshPoints_mesh':960,'MagnetMeshLength':.5,
                'StatorLamMeshLength':1,'RotorLamMeshLength':1}
            for k,v in settings.items():mc.set_variable(k,v)
            if any(abs(mc.get_variable(k)-v)>1e-6 for k,v in settings.items()):raise RuntimeError('Mesh readback mismatch')
            mc.save_to_file(str(folder/(e['id']+'_validation.mot')))
            t=time.perf_counter();mc.do_magnetic_calculation();seconds=time.perf_counter()-t
            csv=folder/(e['id']+'_validation.csv');mc.export_results('EMagnetic',str(csv));values,flag=solver.parse_csv(csv)
            if {k:mc.get_component_material(k) for k in materials}!=materials:raise RuntimeError('Material changed')
            if any(abs(mc.get_variable(k)-v)>1e-6 for k,v in case['expected_native'].items()):raise RuntimeError('Input changed during FEA')
            mc.save_to_file(str(folder/(e['id']+'_validation.mot')))
            graphs={}
            for name in ('TorqueVW','TorqueMsVw'):
                try:
                    gx,gy=mc.get_magnetic_graph(name);graphs[name]={'x':list(map(float,gx)),'y':list(map(float,gy))}
                except Exception as exc:graphs[name]={'error':str(exc)}
            actual=values.get('Torque Ripple (MsVw) [%]')
            row={'id':e['id'],'rotor_id':e['rotor_id'],'predicted_ripple_pct':e['ripple_pct'],'actual_ripple_pct':actual,
                'acceptance':acceptance(e['ripple_pct'],actual),'values':values,'solver_s':seconds,
                'voltage_limit_exceeded':flag,'graphs':graphs,'independent_of_calibration':True}
            write_json(folder/(e['id']+'_validation.json'),row);runs.append(row);write_json(folder/'partial_results.json',runs)
        family=[]
        for rotor in SPM_TYPES:
            rows=[r for r in runs if r['rotor_id']==rotor]
            status='passed_selected_candidates' if rows and all(r['acceptance']['state']=='passed' for r in rows) else 'failed_or_unverified'
            family.append({'rotor_id':rotor,'native_checks':len(rows),'status':status,'production_qualified':False})
        write_json(folder/'result.json',{'status':'completed','family_results':family,'runs':runs,'geometry_failures':failures,
            'elapsed_s':time.time()-started,'all_four_completed':all(f['native_checks']==2 for f in family),
            'acceptance_scope':'Only selected candidates and specified operating point. Not all designs or actual20pct certification.',
            'production_optimizer_connected':False})
        progress('completed',family_results=family)
    except BaseException as exc:
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('failed',error=str(exc));raise
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        if lock:lock.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--calibration-source',type=Path)
    a=p.parse_args();run(a.output,a.calibration_source)
