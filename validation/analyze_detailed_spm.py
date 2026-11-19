"""Offline local DOE audit. No native SDK, FEA, or production model activation."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from study_io import write_json

METRICS={
 'torque_Nm':'Shaft Torque',
 'efficiency_pct':'System Efficiency',
 'phase_resistance_ohm':'Phase Resistance',
 'back_emf_ll_peak_fundamental_V':'Back EMF Line-Line Voltage (peak) (fundamental)',
 'tooth_B_T':'Stator Tooth Flux Density (maximum)',
 'yoke_B_T':'Stator Back Iron Flux Density (maximum)',
 'total_loss_W':'Total Losses (on load)'}
OBSERVED={**METRICS,'torque_ripple_pct':'Torque Ripple (MsVw) [%]'}


def matrix(x,quadratic=False):
    x=np.asarray(x,dtype=float)
    return np.column_stack([np.ones(len(x)),x,x*x] if quadratic else [np.ones(len(x)),x])


def fit_audit(x,y,hold_x,hold_y,quadratic=False):
    a=matrix(x,quadratic);b=matrix(hold_x,quadratic)
    if np.linalg.matrix_rank(a)!=a.shape[1]:raise ValueError('Rank deficient training design')
    coefficients=np.linalg.lstsq(a,np.asarray(y),rcond=None)[0]
    predicted=b@coefficients;actual=np.asarray(hold_y,dtype=float);error=predicted-actual
    return {'coefficients':coefficients.tolist(),'training_count':len(x),'coefficient_count':a.shape[1],
        'training_residual_degrees_of_freedom':len(x)-a.shape[1],
        'holdout_actual':actual.tolist(),'holdout_prediction':predicted.tolist(),
        'holdout_signed_error':error.tolist(),'holdout_max_abs_error':float(np.max(np.abs(error))),
        'holdout_rmse':float(np.sqrt(np.mean(error**2))),
        'holdout_max_abs_relative_error_pct':float(np.max(np.abs(error)/np.maximum(np.abs(actual),1e-12))*100),
        'qualified_for_production':False}


def analyze(folder):
    folder=Path(folder);plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    if result['status'] not in ('completed','completed_with_blocked_cases'):raise ValueError('Completed batch required')
    runs={row['id']:row for row in result['runs']}
    if len(runs)!=len(result['runs']):raise ValueError('Duplicate result IDs')
    groups=[];hashes={}
    for group in plan['groups']:
        cases=group['cases'];available=[c for c in cases if c['id'] in runs]
        if not available:continue
        if len(available)!=len(cases):raise ValueError('Partial topology DOE must not be fitted')
        factors=group['factors'];x=[];values=[];roles=[]
        for case in cases:
            path=folder/(case['id']+'.json');raw=path.read_bytes();hashes[path.name]=hashlib.sha256(raw).hexdigest()
            row=json.loads(raw)
            if row['doe_role']!=case['role'] or row['doe_point']!=case['point']:raise ValueError('DOE identity mismatch')
            if row['native_recipe']!=case['recipe']:raise ValueError('Applied recipe provenance mismatch')
            expected_geometry=case['recipe']['native_variables']
            for key,value in row['geometry_mm'].items():
                if abs(value-expected_geometry[key])>1e-6:raise ValueError('Geometry readback mismatch')
            if row['values']!=runs[case['id']]['values']:raise ValueError('Summary differs from individual result')
            data={key:row['values'][field] for key,field in OBSERVED.items()}
            if not all(np.isfinite(v) for v in data.values()):raise ValueError('Non-finite metric')
            x.append([(case['point'][key]-center)/delta for key,center,delta in factors])
            values.append(data);roles.append(case['role'])
        x=np.asarray(x);train=np.array([role!='independent_holdout' for role in roles]);hold=~train
        audits={key:{name:fit_audit(x[train],[v[key] for v,t in zip(values,train) if t],
                    x[hold],[v[key] for v,t in zip(values,hold) if t],quadratic)
                    for name,quadratic in [('linear',False),('additive_quadratic',True)]} for key in METRICS}
        center=next(i for i,role in enumerate(roles) if role=='training_center')
        effects=[]
        for j,(key,c,delta) in enumerate(factors):
            lo=next(i for i,v in enumerate(x) if np.allclose(v,-np.eye(len(factors))[j]))
            hi=next(i for i,v in enumerate(x) if np.allclose(v,np.eye(len(factors))[j]))
            effects.append({'factor':key,'low':c-delta,'center':c,'high':c+delta,
                'responses':{metric:{'low':values[lo][metric],'center':values[center][metric],
                    'high':values[hi][metric],'high_minus_low':values[hi][metric]-values[lo][metric],
                    'central_slope_per_input_unit':(values[hi][metric]-values[lo][metric])/(2*delta)} for metric in OBSERVED}})
        groups.append({'shape':group['shape'],'factor_order':[v[0] for v in factors],
            'sample_count':len(cases),'training_count':int(train.sum()),'holdout_count':int(hold.sum()),
            'holdout_ids':[c['id'] for c,h in zip(cases,hold) if h],
            'holdout_normalized_coordinates':x[hold].tolist(),
            'holdouts_outside_axial_training_convex_hull':(np.abs(x[hold]).sum(axis=1)>1+1e-9).tolist(),
            'observed_ranges':{key:{'min':min(v[key] for v in values),'max':max(v[key] for v in values)} for key in OBSERVED},
            'local_axis_effects':effects,'model_audits':audits,
            'ripple_model_fitted':False,'production_model_activated':False})
    return {'schema':'detailed-spm-offline-audit-v1','source_folder':str(folder.resolve()),
        'source_sha256':hashes,'groups':groups,'new_motorcad_solves':0,
        'policy':'Diagnostic fits only. No automatic qualification, optimizer integration or input-bound changes.',
        'limitations':['Only three holdouts per shape; no statistical reliability certification.',
            'Additive quadratic training is saturated (nine samples, nine coefficients).',
            'Pairwise interactions are absent from the fitted basis and not identifiable from axial training.',
            'Holdouts lie inside factor bounds but outside the axial training convex hull.',
            'Fixed geometry envelope, winding, current, speed and temperature; no scaling to other conditions.',
            'Ripple is observed only; no ripple predictor is fitted. Inductance is not used.']}


def write_report(data,path):
    lines=['# 상세 SPM DOE 분석','',
        '새 Motor-CAD 해석 없이 기존 결과를 분석했다. 생산용 성능 모델 활성화와 프로그램 입력 범위 변경은 하지 않았다.',
        '', '## 핵심 판단', '',
        '고정된 국소 조건에서는 토크·효율·저항·역기전력·B의 확인점 오차가 작았다. 다만 선형식과 가산2차식의 차이가 작고, 2차식이 일관되게 우수하지 않았다. 지금 자료만으로 복잡한 모델이 더 낫다고 판단하지 않는다.', '',
        '슬롯 깊이9.4→10.6mm 변화에서 요크B가 약0.14T, 리플이 약42~49%p 증가했다. 따라서 요크를 두껍게 할 슬롯 깊이 감소가 우선 검토 방향이다. 반대로 치B는 약0.06T 감소했으므로 슬롯을 얕게 만들 때 치 포화가 악화될 가능성을 함께 확인해야 한다. 치 폭6.3→7.5mm 증가는 치B를 약0.18~0.19T 낮췄지만 요크B는 약0.02~0.03T 높였다. 두 인자를 함께 검토할 이유가 여기에 있다.', '',
        '슬롯 입구 확대는 이번 축 방향 관측에서 리플을 약13~15%p 줄였으나, 포화를 해결할 정도의 B 개선은 없었다. 극호 축소는 요크B 감소 방향이지만 토크 손실을 동반했다. 이 수치는 중심점에서 한 인자씩 바꾼 결과이며 조합 효과를 보증하지 않는다.',
        '', '## 별도 확인점 오차', '',
        '각 형상에서 학습 9점과 확인 3점을 분리했다. 아래는 확인점 3개 중 최대 절대 오차다. 효율 단위는 %p이며, 나머지는 출력 자체의 단위다.', '',
        '| 형상 | 출력 | 선형 모델 오차 | 가산 2차 모델 오차 |', '|---|---|---:|---:|']
    for group in data['groups']:
        for metric in ('torque_Nm','efficiency_pct','phase_resistance_ohm','back_emf_ll_peak_fundamental_V','tooth_B_T','yoke_B_T'):
            a=group['model_audits'][metric]
            lines.append(f"| {group['shape']} | {metric} | {a['linear']['holdout_max_abs_error']:.6g} | {a['additive_quadratic']['holdout_max_abs_error']:.6g} |")
    lines+=['','가산 2차식은 y=c+Σaᵢxᵢ+Σbᵢxᵢ²이다. 9개 계수를 학습 9점에 맞추므로 학습 오차가 작다는 것은 정확도의 증거가 아니다. 인자 간 교차항은 포함하지 않는다. 확인점은 입력 범위 내부지만 축 방향 학습점의 볼록껍질 밖에 있다. 따라서 확인점 오차는 인자 조합에 대한 제한된 점검으로만 해석한다.',
        '', '## 국소 인자 영향', '',
        '다른 인자를 중심에 고정한 상태에서 낮은 값→높은 값의 변화다. 전체 탐색 범위의 영향도 순위나 인과 일반화가 아니다. 리플은 원시 관측 변화만 기록하며 예측식을 만들지 않았다.', '',
        '| 형상 | 인자 (낮음→높음) | 토크 변화 Nm | 효율 변화 %p | 치 B 변화 T | 요크 B 변화 T | 리플 변화 %p |',
        '|---|---|---:|---:|---:|---:|---:|']
    for group in data['groups']:
        for effect in group['local_axis_effects']:
            r=effect['responses'];v=[r[key]['high_minus_low'] for key in ('torque_Nm','efficiency_pct','tooth_B_T','yoke_B_T','torque_ripple_pct')]
            lines.append(f"| {group['shape']} | {effect['factor']} ({effect['low']:g}→{effect['high']:g}) | "+' | '.join(f'{z:+.5g}' for z in v)+' |')
    lines+=['','## 판단과 다음 순서', '',
        '관측한 24점은 모두 리플20% 및 최대B1.8T 조건을 만족하지 않는다. 이는 관측점의 결과이며 전체 연속 탐색 범위가 불가능하다는 증명은 아니다.', '',
        '1. 이번 오차와 국소 영향 방향을 기준으로 성능 모델의 적용 범위와 허용 오차 정책을 정한다. 임의의 오차 임계값으로 자동 합격시키지 않는다.',
        '2. 치 폭 증가·슬롯 깊이 감소로 치와 요크의 포화를 완화할 가능성을 검토하되, 슬롯 면적·권선 충전율·저항 변화와 함께 판단한다. 지금은 입력 범위를 자동 확대하지 않는다.',
        '3. 확인점 오차가 큰 출력은 추가 교차 인자점이 필요하다. 기존 확인점을 학습으로 돌려 쓰고 같은 점으로 정확도를 주장하지 않는다.',
        '4. Breadloaf 코너 형상을 확인한 다음 보류된14회 해석을 진행한다. 실제 실행은 별도로 시작한다.',
        '5. 독립 확인이 끝난 국소 평가기만 최적화 엔진에 연결한다. 리플 예측 기능 보류와 미검증 값 분리 정책은 유지한다.',
        '', '현재 시험 범위는 치 폭6.3~7.5mm, 슬롯 깊이9.4~10.6mm, 슬롯 입구1.6~2.4mm, 극호110~130전기각이다. 이 밖의 값을 현재 회귀식으로 합격 판정하지 않는다. 먼저 이 범위 내 조합의 교차 영향을 확인하고, 그래도 포화 여유가 부족하면 범위를 새로 설정해 별도 교정해야 한다. 현 시점에서 임의의 새 범위를 기본값으로 지정하지 않았다.',
        '', '고정 조건은 D85×L20, 4극12슬롯, gap0.5mm, 6턴, 도선1.8mm, Delta, 선전류 첨두40A, 3500rpm, 20℃이다. 이번 효율·토크를 요구 토크0.5Nm에 맞춘 최적화 결과로 제시하지 않는다. 열·구조 해석은 제외 상태다.',
        '', '상세 좌표·계수·확인점별 실제값과 예측값·원본 해시는 analysis.json에 저장했다.']
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();data=analyze(args.source);args.output.mkdir(parents=True,exist_ok=True)
    write_json(args.output/'analysis.json',data);write_report(data,args.output/'REVIEW_KO.md')
    print(json.dumps({'groups':len(data['groups']),'samples':sum(g['sample_count'] for g in data['groups']),'new_motorcad_solves':0}))
