"""Bounded diagnostic search of local B fits. Never certifies feasibility."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from scipy.optimize import differential_evolution
from analyze_detailed_spm import matrix
from plan_spm_interaction import basis
from detailed_spm_recipe import compile_recipe
from dimension_grid import mm
from study_io import write_json


def decode(x,factors):
    if len(x)!=4 or len(factors)!=4 or not np.all(np.isfinite(x)) or np.any(np.abs(x)>1+1e-9):raise ValueError('Four finite coordinates within the local box required')
    values={key:mm(center+delta*z) if key.endswith('_mm') else float(center+delta*z)
        for (key,center,delta),z in zip(factors,x)}
    normalized=np.array([(values[key]-center)/delta for key,center,delta in factors])
    return values,normalized


def search(group,plan_group,model_name):
    factors=plan_group['factors'];count=0;unique=set()
    coefficients={k:np.array(v[model_name]['coefficients']) for k,v in group['metrics'].items()}
    def predict(x):
        features=basis([x])[0] if model_name=='focused_interaction' else matrix([x],True)[0]
        return {key:float(features@coef) for key,coef in coefficients.items()}
    def objective(x):
        nonlocal count
        point,z=decode(x,factors);count+=1;unique.add(tuple(point.values()))
        p=predict(z)
        return max(p['tooth_B_T'],p['yoke_B_T'])
    started=time.perf_counter();results=[]
    for seed in (11,29):
        r=differential_evolution(objective,[(-1,1)]*4,seed=seed,maxiter=50,popsize=8,polish=False,tol=1e-7,workers=1)
        results.append(r)
    r=min(results,key=lambda v:v.fun);point,z=decode(r.x,factors);p=predict(z)
    recipe=compile_recipe(plan_group['request'],point)
    score=max(p['tooth_B_T'],p['yoke_B_T'])
    return {'model':model_name,'point':point,'predictions':p,'predicted_tooth_yoke_max_B_T':score,
        'predicted_tooth_yoke_limit_met':score<=1.8,'candidate_on_boundaries':[key for key,coord in zip([f[0] for f in factors],z) if abs(coord)>.999],
        'normalized_point':z.tolist(),'optimizer_converged':bool(r.success),'optimizer_message':str(r.message),
        'objective_evaluations':count,'unique_points':len(unique),'elapsed_s':time.perf_counter()-started,
        'recipe':recipe,'target_met':False,'global_minimum_certified':False,
        'unverified':['candidate FEA','tooth tip and rotor maximum B','PWM ripple','torque ripple','other operating points'],
        'scope':'Best point from two bounded DE seeds under one local fit. Not a proof of feasibility or infeasibility.'}


def run(analysis_path,plan_path):
    raw=Path(analysis_path).read_bytes();analysis=json.loads(raw)
    if analysis['status']!='complete' or analysis['completed_fea']!=14:raise ValueError('Complete audited interaction batch required')
    for name,digest in analysis['source_sha256'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest:raise ValueError('Audited native result changed: '+name)
    plan=json.loads(Path(plan_path).read_text(encoding='utf-8'));groups=[]
    for group in analysis['groups']:
        pg=next(g for g in plan['groups'] if g['shape']==group['shape'])
        searches=[search(group,pg,model) for model in ('old_additive_quadratic','augmented_additive_quadratic','focused_interaction')]
        groups.append({'shape':group['shape'],'searches':searches,
            'next_action':'range_adjustment_review' if all(not s['predicted_tooth_yoke_limit_met'] for s in searches) else 'native_validation_before_range_expansion'})
    return {'schema':'spm-saturation-diagnostic-v1','analysis_sha256':hashlib.sha256(raw).hexdigest(),
        'groups':groups,'new_motorcad_solves':0,'production_model_activated':False,'input_bounds_changed':False,
        'limitations':['Only tooth/yoke B are minimized; full iron B, ripple and drive feasibility are not qualified.',
            'Discrete length rounding uses 0.1mm. Pole arc remains a continuous electrical-angle input.',
            'DE best score is not a certified global optimum; local fit error is not a confidence bound.',
            'Three model variants are sensitivity checks, not independent ensembles or formal uncertainty estimates.',
            'Fixed D85 L20 gap0.5, speed3500rpm, current40A linepeak, 20C, Delta and original material pair.']}


def report(data,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);write_json(folder/'diagnostic.json',data)
    lines=['# 상세 형상 포화 진단','',
        'Motor-CAD 추가 실행 없이, 기존 범위 안에서 국소 회귀식의 치·요크 최대B를 낮추는 방향을 탐색했다. 합격 판정이나 전역 최적성 증명은 아니다.', '',
        '| 형상 | 모델 | 치 폭 mm | 슬롯 깊이 mm | 슬롯 입구 mm | 극호 전기각 | 치·요크 최대B 예측 T |',
        '|---|---|---:|---:|---:|---:|---:|']
    for group in data['groups']:
        for s in group['searches']:
            p=s['point'];vals=[p[k] for k in ('tooth_width_mm','slot_depth_mm','slot_opening_mm','pole_arc_ed')]
            lines.append(f"| {group['shape']} | {s['model']} | "+' | '.join(f'{v:.5g}' for v in vals)+f" | {s['predicted_tooth_yoke_max_B_T']:.6f} |")
        lines+=['',f"{group['shape']} 후속 분류: {group['next_action']}.", '']
    lines+=['','## 다음 단계', '',
        '세 식의 낮은B 후보가 모두 한도를 넘거나 경계에 몰리면 기존 범위를 그대로 반복하기보다 범위·고정조건 재설정 검토가 우선이다. 예측 한도 이하 후보가 나오더라도 해당 실제 형상은 FEA 확인 전이다. 치끝·로터 B와 리플은 이 탐색에서 검증하지 않는다.', '',
        '범위 재검토에서는 치 폭·요크 두께·보어·자석 두께·공극·전류 부하를 함께 검토하되, 범위 밖 성능을 기존 식으로 외삽해 합격시키지 않는다. 철심·슬롯 공간·토크 요구를 함께 확인할 새 기준 해석이 필요하다. 기존 프로그램 기본값과 최적화 모델은 바꾸지 않았다.', '',
        '토크리플 예측 기능은 보류 상태다. Breadloaf14회도 최소 코너 두께 확인 대기로 유지한다. 열·구조·스큐 검증은 제외한다.']
    (folder/'REVIEW_KO.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--analysis',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();data=run(a.analysis,a.plan);report(data,a.output)
    print(json.dumps({'groups':[(g['shape'],g['next_action']) for g in data['groups']],'new_motorcad_solves':0}))
