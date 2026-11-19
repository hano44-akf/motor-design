"""Formula-only topology study and persisted deferred verification manifest.

No native solver, application launch, or network access is performed here.
Pending tasks are a dependency plan, not executable Motor-CAD jobs.
"""
import argparse
import copy
import hashlib
import json
import math
import time
from pathlib import Path
from dimension_grid import mm
from geometry_adapters import build_geometry
from rotor_catalog import pole_slot_pairs, preflight, resolve_rotor
from formula_job import run_formula, validate_formula


def write(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def geometry_draft(request, pair):
    """Seed only: preserve radial proportions; scale tangential tooth allocation.

    This is NOT a magnetic design rule or saturation/slot-fill verification.
    Only the two implemented surface templates can use this seed recipe.
    """
    if resolve_rotor(request['spm'])['id'] not in ('surface_radial','surface_parallel'):
        return {'status':'geometry_adapter_pending','geometry_mm':None}
    bounds=request['bounds']
    d,l=[mm((lo+hi)/2) for lo,hi in bounds[:2]]
    g=build_geometry(request['spm'],d,l)
    from operating_control import airgap_bounds
    lo,hi=airgap_bounds(request)
    overrides={'Airgap':mm((lo+hi)/2),
        'Tooth_Width':mm(g['Tooth_Width']*12/pair['slots']),
        'Slot_Opening':mm(g['Slot_Opening']*12/pair['slots'])}
    if min(overrides.values())<=0:return {'status':'seed_dimensions_invalid','geometry_mm':None}
    g=build_geometry(request['spm'],d,l,overrides)
    pitch=math.pi*g['Stator_Bore']/pair['slots']
    return {'status':'unverified_geometry_seed','geometry_mm':g,
        'pole_arc_electrical_deg':120,'skew_enabled':False,
        'bore_slot_pitch_mm':pitch,
        'tooth_plus_opening_below_bore_pitch':g['Tooth_Width']+g['Slot_Opening']<pitch,
        'scope':'Initialization only; tangential dimensions scaled by slot count. Tooth/yoke flux, exact slot area, end turns, fill and rotor strength unverified.'}


def make_tasks(key, request, draft, winding, candidate_ids):
    items=[]
    def add(code,title,depends,outputs,method='Motor-CAD',extra=None):
        item={'id':key+'_'+code,'topology_id':key,'title':title,'status':'pending',
              'depends_on':[key+'_'+v for v in depends],'method':method,
              'required_outputs':outputs,'execution_enabled':False,
              'acceptance_status':'not_evaluated','candidate_ids':candidate_ids}
        if extra:item.update(extra)
        items.append(item)
    add('mapping','형상·권선·재질·결선 입력 및 읽기 대조',[],
        ['native geometry readback','slot/phase/sign/coil-span/layer table','material names','connection/strands/parallel paths'],
        extra={'geometry_seed':draft,'analytical_winding':winding,
               'acceptance':'Compare every mapped input; candidate winding is not a native readback.'})
    add('reference','조합별 기준 성능 및 단부 길이 확인',['mapping'],
        ['phase/line RMS and peak conventions','EMF waveform/FFT','flux linkage','R at reference temperature','Ld/Lq and current','mean torque','copper/iron/other losses','MLT','slot area/fill'])
    add('cogging','무전류 코깅 및 전류 크기·각도 스윕',['reference'],
        ['torque waveform on common rotor-angle grid','mean/peak-to-peak','harmonic amplitude and phase','current-angle convention'],
        extra={'current_scale_factors':[0,.25,.5,1,1.5],'note':'Zero-current ripple percentage is undefined; save absolute torque peak-to-peak. Angle bounds and current limits must be supplied before execution.'})
    add('convergence','메시·각도 분해능 수렴',['cogging'],
        ['mean torque change','torque peak-to-peak change','B region definition','loss change'],
        extra={'electrical_samples_per_cycle':[60,120,240,360],
               'acceptance':'Numerical tolerance and mesh levels must be established before automatic pass/fail.'})
    add('surrogate','국소 수식 모델 DOE 및 독립 오차 확인',['reference','convergence'],
        ['geometry DOE inputs','held-out Kt/R/L/loss errors','validity bounds','model version'],
        extra={'note':'Re-optimize new topology only after its model is fitted; one reference point does not validate the full search domain.'})
    add('candidate','선택 후보의 전압·온도·운전점 성능 검증',['surrogate'],
        ['shaft torque','efficiency','terminal fundamental voltage','torque ripple','tooth/yoke B','current density','slot fill'],
        extra={'operating_point':request['operating_point'],'temperatures_C':request['temperatures_C'],
               'limits':{'flux_density_max_T':request.get('flux_density_max_T',1.8),
                         'torque_ripple_max_pct':request['operating_point'].get('torque_ripple_max_pct',20)},
               'note':'Unknowns remain verification_incomplete; final selected models may differ from current formula candidates.'})
    add('pwm','PWM 전류 리플·Delta 순환전류',['reference'],
        ['HF/differential inductance','zero-sequence impedance','phase EMF triplen harmonics','PWM current waveform','delta loop loss'],
        method='Circuit coupling / supported external solver',
        extra={'limit_pct':request.get('pwm_current_ripple_max_pct',15),
               'note':'Prescribed sinusoidal-current FEA alone is insufficient. Circuit/inverter parameters are required.'})
    add('demagnetization','감자 검증',['candidate'],
        ['demagnetization margin at specified magnet temperature and negative Id'],
        method='Motor-CAD electromagnetic / supported demagnetization solver',
        extra={'note':'Prescribed temperatures and current limits required; thermal and structural analyses excluded by user.'})
    return items


def run_study(request, folder, optimize_available=True):
    folder=Path(folder).resolve()
    # Never overwrite a queue that may already contain manually recorded results.
    folder.mkdir(parents=True,exist_ok=False)
    write(folder/'request.json',request)
    start=time.perf_counter();reviews=[];tasks=[];candidates=[]
    for pair in pole_slot_pairs(request):
        key=f"p{pair['poles']}_s{pair['slots']}"
        sub=copy.deepcopy(request);sub['pole_slot_candidates']=[pair]
        review=preflight(sub);pr=review['pole_slot_review'][0]
        entry={'id':key,'pair':pair,'review':pr,'blocking_reasons':review['blocking_reasons']}
        excluded=(pr['pwm_check'] and not pr['pwm_check']['passes']) or not pr['winding_analysis']['balanced']
        if excluded:
            entry['status']='excluded_by_analytical_screen';reviews.append(entry);continue
        draft=geometry_draft(sub,pair);entry['geometry_seed']=draft
        ids=[]
        # Shared validation remains authoritative; missing calibration is deferred.
        try:validate_formula(sub)
        except ValueError as exc:
            entry['status']='deferred_model_preparation';entry['execution_blocker']=str(exc)
        else:
            entry['status']='formula_ready'
            if optimize_available:
                result=run_formula(sub,folder/key)
                entry.update(status='formula_completed',timings=result['timings'],search_statistics=result['search_statistics'])
                for model in result['results']:
                    model=copy.deepcopy(model);model['id']=key+'_'+model['id'];model['topology_id']=key
                    candidates.append(model);ids.append(model['id'])
        tasks.extend(make_tasks(key,sub,draft,pr['winding_analysis'],ids))
        reviews.append(entry)
    # Compare only physically screened predictions; missing topology data never
    # becomes zero loss or an apparently superior Pareto candidate.
    feasible=[m for m in candidates if m['prediction']['target_met']]
    for model in candidates:
        p=model['prediction'];v=p['volume_mm3'];loss=p['copper_loss_W']+p['other_loss_W']
        model['formula_pareto_candidate']=model in feasible and not any(
            other['prediction']['volume_mm3']<=v and other['prediction']['copper_loss_W']+other['prediction']['other_loss_W']<=loss and
            (other['prediction']['volume_mm3']<v or other['prediction']['copper_loss_W']+other['prediction']['other_loss_W']<loss)
            for other in feasible if other is not model)
    queue={'schema':'deferred-motor-validation-v1','motorcad_solves':0,'execution_enabled':False,
           'request_sha256':hashlib.sha256((folder/'request.json').read_bytes()).hexdigest(),
           'scope':'Dependency checklist only; no automatic execution. Other solvers/input preparation may be required.',
           'tasks':tasks}
    from verification_scope import apply_scope
    queue=apply_scope(queue)
    result={'schema':'topology-formula-study-v1','motorcad_solves':0,'topologies':reviews,'candidates':candidates,
            'all_topologies_optimized':all(r['status'] in ('formula_completed','excluded_by_analytical_screen') for r in reviews),
            'session_wall_s':time.perf_counter()-start,'pending_task_count':len(tasks)}
    write(folder/'validation_queue.json',queue);write(folder/'result.json',result)
    lines=['# Motor-CAD 등 일괄 검증 대기 목록','',
           '해석 실행 0회. 이 파일은 검증 계획이며 실행 스크립트가 아닙니다. 미확인 결과는 합격으로 처리하지 않습니다.','',
           '|ID|검증 항목|선행 항목|수행 도구|상태|','|---|---|---|---|---|']
    lines += [f"|{t['id']}|{t['title']}|{', '.join(t['depends_on']) or '-'}|{t['method']}|대기|" for t in tasks]
    lines+=['','세부 입력·출력·판정 조건과 권선표/형상 초안은 validation_queue.json에 저장했습니다.',
            '새 조합은 기준 모델 보정 후 최적화를 다시 수행하고 최종 후보를 검증해야 합니다. 모든 항목을 서로 독립적인 해석으로 한 번에 실행할 수는 없습니다.']
    (folder/'VALIDATION_QUEUE_KO.md').write_text('\n'.join(lines),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--plan-only',action='store_true')
    args=parser.parse_args()
    result=run_study(json.loads(args.request.read_text(encoding='utf-8')),args.output,not args.plan_only)
    print(json.dumps({'pending_tasks':result['pending_task_count'],'formula_models':len(result['candidates']),
                      'wall_s':result['session_wall_s'],'motorcad_solves':0}))
