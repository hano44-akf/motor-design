"""Gated Custom Drive +/- phase-current / flux-linkage development study.

First case must reproduce the requested currents before later cases run.
This measures data for phase-index identification, not design performance.
"""
import argparse
import contextlib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import numpy as np
from study_io import write_json

ROOT=Path(__file__).resolve().parent
SETTINGS={'DriveType_BPM':0,'BPMDriveMode':2,'CustomDriveDefinition':0,'CustomDriveCyclePointReduction':1,
          'MagneticSolverMethod':1,'FEASolutionCycle':1,
          'TorqueCalculation':True,'TorquePointsPerCycle':24,'TorqueNumberCycles':1,
          'BackEMFCalculation':False,'InductanceCalc':False,'CoggingTorqueCalculation':False,
          'TorqueSpeedCalculation':False,'DemagnetizationCalc':False,'BPMShortCircuitCalc':False,
          'ElectromagneticForcesCalc_OC':False,'ElectromagneticForcesCalc_Load':False}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wave_text(angle,current):
    a=np.asarray(angle);i=np.asarray(current)
    if i.shape!=(len(a),3) or a[0]!=0 or a[-1]!=360 or not np.all(np.diff(a)>0):raise ValueError('Full-cycle 3-phase waveform required')
    if not np.all(np.isfinite(i)):raise ValueError('Finite currents required')
    return 'ElectricalAngle Phase1 Phase2 Phase3\n'+'\n'.join(' '.join(format(float(v),'.16g') for v in [x,*row]) for x,row in zip(a,i))+'\n'


def prepare(experiment,output):
    experiment=Path(experiment).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Fresh experiment folder required')
    old=json.loads((experiment/'plan.json').read_text(encoding='utf-8'))
    data=json.loads((experiment/'result.json').read_text(encoding='utf-8'));g=data['graphs']
    angle=np.array(g['SmallSignalInductanceCurrentPh1']['x'])
    base=np.column_stack([g[f'SmallSignalInductanceCurrentPh{i}']['y'] for i in range(1,4)])
    output.mkdir(parents=True);cases=[]
    for phase in range(3):
        for sign in (1,-1):
            currents=base.copy();currents[:,phase]+=sign*.1
            # Native Custom Drive's electrical-angle origin was measured to
            # lag the Small Signal bias graph by 90 ED. Rotate the file, then
            # verify actual solved currents against the unrotated target.
            shifted=(angle+90)%360
            file_currents=np.column_stack([np.interp(shifted,angle,currents[:,j]) for j in range(3)])
            name=f'phase{phase+1}_'+('plus' if sign>0 else 'minus');path=output/(name+'.txt')
            path.write_text(wave_text(angle,file_currents),encoding='ascii')
            # In this v261 Custom Drive path, measured scaling uses the first
            # line pair (file phase1 - phase2), not max over all three lines.
            desired_peak_line=float(np.max(abs(currents[:,0]-currents[:,1])))
            cases.append({'id':name,'perturbed_phase':phase+1,'offset_A':sign*.1,
                          'wave_file':str(path),'wave_sha256':sha(path),
                          'expected_angle_ed':angle.tolist(),'expected_phase_current_A':currents.tolist(),
                          'input_file_phase_current_A':file_currents.tolist(),
                          'peak_line_current_setting_A':desired_peak_line})
    plan={'schema':'breadloaf-custom-flux-probe-v1','source_experiment':str(experiment),
          **{k:old[k] for k in ('source_batch','source_model','source_database','source_snapshot','model_sha256','database_sha256','snapshot_sha256','candidate_id')},
          'settings':SETTINGS,'cases':cases,'planned_fea':6,'per_case_timeout_s':300,
          'file_angle_origin_correction_ed':90,
          'angle_origin_evidence':'outputs/breadloaf_phase_mapping_v2_20261105/phase1_plus/result.json: all three solved phase currents equal file(theta-90 ED).',
          'estimated_duration_minutes':[3,8],'estimate_basis':'Provisional 24-point custom multi-static runs; not measured yet.',
          'gate':'Stop after any missing flux/current output or imposed-current mismatch. No blind continuation/retry.',
          'current_readback_tolerance_A':1e-5,'scope':'Diagnostic +/-0.1A phase perturbations, not a new feasible design. Central flux/current differences pending.',
          'mapping_qualified':False,'pwm_ripple_certified':False}
    write_json(output/'plan.json',plan);return plan


def resume_validated(source,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists():raise ValueError('Fresh continuation folder required')
    plan=json.loads((source/'plan.json').read_text(encoding='utf-8'))
    result=json.loads((source/'result.json').read_text(encoding='utf-8'))
    validated=[r for r in result['outcomes'] if r['data_validated']]
    ids={r['id'] for r in validated}
    pending=[c for c in plan['cases'] if c['id'] not in ids]
    if len(validated)!=4 or {c['id'] for c in pending}!={'phase3_plus','phase3_minus'}:
        raise ValueError('Continuation requires four validated phase1/2 cases and phase3 pair pending')
    for case in pending:
        current=np.array(case['expected_phase_current_A'])
        case['peak_line_current_setting_A']=float(np.max(abs(current[:,0]-current[:,1])))
    plan.update(cases=pending,planned_fea=2,total_mapping_cases=6,reused_outcomes=validated,
                resumed_from=str(source),resumed_result_sha256=sha(source/'result.json'),
                normalization_evidence='phase3_plus measured uniform scale = PeakCurrent / peak(file phase1 - phase2); correct setting uses that reference.',
                estimated_duration_minutes=[1,3],estimate_basis='Prior custom runs measured about 15 seconds/case including startup; allow margin.')
    output.mkdir();write_json(output/'plan.json',plan);return plan


def worker(folder,index):
    from low_voltage import start
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'));case=plan['cases'][index]
    for key,h in (('source_model','model_sha256'),('source_database','database_sha256'),('source_snapshot','snapshot_sha256')):
        if sha(plan[key])!=plan[h]:raise ValueError('Frozen source changed: '+key)
    if sha(case['wave_file'])!=case['wave_sha256']:raise ValueError('Waveform changed')
    work=folder/case['id'];work.mkdir();mc=None;started=time.time()
    try:
        model=work/'custom.mot';db=work/'working_materials.mdb'
        shutil.copy2(plan['source_model'],model);shutil.copy2(plan['source_database'],db)
        mc,_=start();mc.load_from_file(str(model));mc.select_material_database(str(db),False);mc.clear_message_log()
        source=json.loads(Path(plan['source_snapshot']).read_text(encoding='utf-8'))
        for k,v in source['expected_native'].items():
            if abs(mc.get_variable(k)-v)>1e-6:raise ValueError('Source input mismatch: '+k)
        for k,v in plan['settings'].items():mc.set_variable(k,v)
        mc.load_custom_drive_cycle(case['wave_file']);mc.set_variable('PeakCurrent',case['peak_line_current_setting_A'])
        readback={k:mc.get_variable(k) for k in plan['settings']}
        if readback!=plan['settings']:raise ValueError('Custom settings readback mismatch')
        count=int(mc.get_variable('CustomDriveCyclePoints'))
        if count!=len(case['expected_angle_ed']):raise ValueError('Custom file row count mismatch: header or endpoint lost')
        for row in range(count):
            if abs(mc.get_array_variable('CustomDriveCycleElectricalAngle',row)-case['expected_angle_ed'][row])>1e-8:raise ValueError('Loaded custom angle mismatch')
            for phase in range(3):
                if abs(mc.get_array_variable_2d('CustomDriveCycleWaveform',row,phase)-case['input_file_phase_current_A'][row][phase])>1e-8:
                    raise ValueError('Loaded custom current mismatch')
        write_json(work/'progress.json',{'phase':'solving_custom_flux','started_unix':started})
        mc.save_to_file(str(model));t=time.perf_counter();mc.do_magnetic_calculation();solver_s=time.perf_counter()-t
        graphs={}
        for prefix in ('PhaseCurrent','FluxLinkageLoadPh'):
            for phase in range(1,4):
                name=prefix+str(phase)
                try:
                    x,y=mc.get_magnetic_graph(name);graphs[name]={'x':list(map(float,x)),'y':list(map(float,y))}
                except Exception as exc:graphs[name]={'error':str(exc)}
        errors=[];max_error=None
        if any(not g.get('x') for g in graphs.values()):errors.append('Required current/flux graph unavailable')
        else:
            all_errors=[]
            for phase in range(3):
                graph=graphs[f'PhaseCurrent{phase+1}'];x=np.array(graph['x']);y=np.array(graph['y'])
                if x.min()>0 or x.max()<360:errors.append('Current graph does not cover expected electrical-angle range');continue
                expected=np.array(case['expected_phase_current_A'])[:,phase]
                actual=np.interp(case['expected_angle_ed'],x,y);all_errors.append(float(abs(actual-expected).max()))
            if all_errors:max_error=max(all_errors)
            if max_error is not None and max_error>plan['current_readback_tolerance_A']:errors.append('Imposed currents differ from requested phase perturbation')
        mc.export_results('EMagnetic',str(work/'custom.csv'));mc.save_to_file(str(model))
        write_json(work/'result.json',{'id':case['id'],'status':'completed','data_validated':not errors,
            'validation_errors':errors,'max_imposed_current_error_A':max_error,'graphs':graphs,'readback':readback,
            'solver_s':solver_s,'elapsed_s':time.time()-started,'mapping_qualified':False})
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()


def supervise(folder):
    import msvcrt
    from run_spm_ripple_recovery import stop_owned
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    if (folder/'progress.json').exists():raise ValueError('Already started')
    started=time.time();rows=[];child=None;lock=(ROOT/'motorcad_execution.lock').open('a+b')
    reused=plan.get('reused_outcomes',[])
    if reused and sha(Path(plan['resumed_from'])/'result.json')!=plan['resumed_result_sha256']:
        raise ValueError('Reused verified evidence changed')
    def progress(status,**extra):write_json(folder/'progress.json',{'status':status,'started_unix':started,'elapsed_s':time.time()-started,
        'planned_fea':len(plan['cases']),'completed_fea':len(rows),'data_validated_cases':sum(r['data_validated'] for r in rows),
        'unattempted_cases':len(plan['cases'])-len(rows),**extra})
    try:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        for index,case in enumerate(plan['cases']):
            progress('running',active_case=case['id'])
            with (folder/(case['id']+'.log')).open('wb') as log:
                child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker','--output',str(folder),'--case-index',str(index)],
                    cwd=ROOT.parent,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                try:code=child.wait(timeout=plan['per_case_timeout_s'])
                except subprocess.TimeoutExpired:stop_owned(child);raise RuntimeError('Custom flux timeout')
            if code:raise RuntimeError('Custom flux worker failed: '+case['id'])
            row=json.loads((folder/case['id']/'result.json').read_text(encoding='utf-8'));rows.append(row)
            if row['data_validated'] and case['id'].endswith('_minus'):
                positive=next((r for r in reused+rows if r['id']==case['id'].replace('_minus','_plus')),None)
                if positive:
                    minimum=pair_self_minimum(positive,row,case['perturbed_phase'])
                    if minimum<=0:
                        row['data_validated']=False
                        row['validation_errors'].append('Self flux/current derivative nonpositive over cycle; possible cycle reconstruction. No continuation.')
            write_json(folder/'partial_results.json',rows)
            if not row['data_validated']:break
        status='completed' if len(rows)==len(plan['cases']) and all(r['data_validated'] for r in rows) else 'stopped_after_input_check'
        write_json(folder/'result.json',{'status':status,'outcomes':reused+rows,'planned_fea':len(plan['cases']),
            'completed_fea':len(rows),'unattempted_cases':len(plan['cases'])-len(rows),'elapsed_s':time.time()-started,
            'reused_validated_cases':len(reused),
            'mapping_qualified':False,'pwm_ripple_certified':False})
        progress(status)
        if status=='completed':review(folder)
    except BaseException as exc:
        if child and child.poll() is None:stop_owned(child)
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('failed');raise
    finally:lock.close()


def launch(folder):
    folder=Path(folder).resolve()
    if (folder/'progress.json').exists() or (folder/'launch.json').exists():raise ValueError('Already launched')
    with (folder/'supervisor.log').open('wb') as log:
        p=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'supervise','--output',str(folder)],
            cwd=ROOT.parent,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    write_json(folder/'launch.json',{'supervisor_pid':p.pid,'waited_for_completion':False});return p.pid


def pair_self_minimum(plus,minus,phase):
    pg=plus['graphs'][f'FluxLinkageLoadPh{phase}'];mg=minus['graphs'][f'FluxLinkageLoadPh{phase}']
    pi=plus['graphs'][f'PhaseCurrent{phase}'];mi=minus['graphs'][f'PhaseCurrent{phase}']
    x=np.asarray(pg['x']);dflux=np.asarray(pg['y'])-np.interp(x,mg['x'],mg['y'])
    di=np.interp(x,pi['x'],pi['y'])-np.interp(x,mi['x'],mi['y'])
    if np.any(abs(di)<1e-8):raise ValueError('Phase perturbation lost')
    return float(np.min(dflux/di))


def review(folder):
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    result_path=folder/'result.json'
    if not result_path.is_file():return {'status':'not_complete','matrix_qualified':False,'new_native_fea':0}
    result=json.loads(result_path.read_text(encoding='utf-8'))
    if result['status']!='completed' or len(result['outcomes'])!=6 or not all(r['data_validated'] for r in result['outcomes']):
        report={'status':'input_validation_incomplete','matrix_qualified':False,'new_native_fea':0,
                'completed_fea':result['completed_fea'],'unattempted_cases':result['unattempted_cases']}
    else:
        rows={r['id']:r for r in result['outcomes']};angle=np.array(plan['cases'][0]['expected_angle_ed'])
        delta_i=np.empty((len(angle),3,3));delta_flux=np.empty_like(delta_i)
        for axis in range(3):
            plus=rows[f'phase{axis+1}_plus'];minus=rows[f'phase{axis+1}_minus']
            for response in range(3):
                for prefix,container in (('PhaseCurrent',delta_i),('FluxLinkageLoadPh',delta_flux)):
                    p=plus['graphs'][prefix+str(response+1)];m=minus['graphs'][prefix+str(response+1)]
                    if min(p['x'])>0 or max(p['x'])<360 or min(m['x'])>0 or max(m['x'])<360:
                        raise ValueError('Incomplete current/flux angular domain')
                    container[:,response,axis]=np.interp(angle,p['x'],p['y'])-np.interp(angle,m['x'],m['y'])
        if np.any(np.linalg.matrix_rank(delta_i)<3):raise ValueError('Perturbation directions not independent')
        jacobian=delta_flux@np.linalg.inv(delta_i)
        diagonal=np.diagonal(jacobian,axis1=1,axis2=2)
        bad=np.flatnonzero(np.any(diagonal<=0,axis=1))
        report={'status':'blocked_by_flux_cycle_reconstruction' if len(bad) else 'central_jacobian_assembled','angle_ed':angle.tolist(),
                'self_derivative_minimum_raw':float(diagonal.min()),
                'nonpositive_self_derivative_angles_ed':angle[bad].tolist(),
                'response_rows_excitation_columns_explicit':True,
                'matrix_native_flux_units_per_A':jacobian.tolist(),
                'max_current_difference_condition_number':float(np.linalg.cond(delta_i).max()),
                'max_raw_reciprocity_difference':float(abs(jacobian-jacobian.transpose(0,2,1)).max()),
                'units_status':'Raw flux graph unit must be confirmed before SI PWM use',
                'scope':'Directly labelled current/flux central differences; no arbitrary native graph-index choice or symmetrisation.',
                'matrix_qualified':False,'pwm_ripple_certified':False,'new_native_fea':0}
        from breadloaf_pwm_preview import csv_number
        end,unit,rounding=csv_number(folder/plan['cases'][0]['id']/'custom.csv','Armature End Winding Inductance_(Hanselman)')
        if unit!='mH':raise ValueError('Unexpected end-inductance unit')
        one=np.ones(3)/np.sqrt(3);common=np.einsum('i,nij,j->n',one,jacobian,one)
        report['unit_and_end_anchor']={'raw_common_mode_min':float(common.min()),'raw_common_mode_max':float(common.max()),
            'native_end_inductance_H':end*.001,'native_csv_rounding_H':rounding*.001,
            'max_H_interpretation_anchor_difference':float(abs(common-end*.001).max()),
            'interpretation':'H/Wb-per-A interpretation matches Native end anchor; case-specific numerical evidence, not a universal API declaration.',
            'end_inclusion_policy':'Direct flux-response matrix already contains the common-mode end term. Do not add end self-inductance twice.'}
    write_json(folder/'mapping_review.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','start','worker','supervise','review','resume-validated']);p.add_argument('--output',required=True)
    p.add_argument('--experiment');p.add_argument('--case-index',type=int);a=p.parse_args()
    if a.command=='prepare':r=prepare(a.experiment,a.output);print(json.dumps({'planned_fea':r['planned_fea'],'estimated_duration_minutes':r['estimated_duration_minutes']}))
    elif a.command=='resume-validated':r=resume_validated(a.experiment,a.output);print(json.dumps({'planned_fea':r['planned_fea'],'reused_cases':len(r['reused_outcomes'])}))
    elif a.command=='start':print(json.dumps({'supervisor_pid':launch(a.output),'waited_for_completion':False}))
    elif a.command=='worker':worker(a.output,a.case_index)
    elif a.command=='review':print(json.dumps(review(a.output),indent=2))
    else:supervise(a.output)
