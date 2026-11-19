"""Build an evidence-based old/new comparison; never launch Motor-CAD."""
from pathlib import Path
import hashlib
import json
import math
import statistics
import sys

ROOT=Path(__file__).resolve().parent


def load(p):return json.loads(p.read_text(encoding='utf-8'))


def summary(c,old=False):
    run=next(r for r in c['runs'] if r['design']['voltage_V']==12)
    d=run['design'];v=run['values'];g=run.get('geometry_mm',{})
    return {'id':c['id'],'objective':c['objective'],'stator_od_mm':g.get('Stator_Lam_Dia',d['diameter_mm']),
            'housing_od_mm':g.get('Housing_Dia',140*d['diameter_mm']/130),
            'stack_mm':g.get('Stator_Lam_Length',d['length_mm']),
            'turns':d['turns_per_coil'],'wire_mm':d['wire_diameter_mm'],
            'torque_Nm':v['Shaft Torque'],'efficiency_pct':v['System Efficiency'],
            'Kt_MotorCAD_Nm_per_A_line_peak':v.get('Torque Constant (Kt)'),
            'shaft_torque_per_phase_rms_A':v['Shaft Torque']/v['Phase Current (rms)'],
            'shaft_torque_per_line_rms_A':v['Shaft Torque']/v['Line Current (rms)'],
            'ripple_pct':v['Torque Ripple (MsVw) [%]'],
            'max_iron_B_T':max(v[k] for k in ['Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)',
                                               'Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)']),
            'phase_R_ohm':v['Phase Resistance'],'Ld_mH':v['D Axis Inductance'],'Lq_mH':v['Q Axis Inductance'],
            'terminal_peak_V':v['Line-Line Terminal Voltage (peak)'],
            'geometry_mm':g,'source_label':run['label'],
            'new_requirements_met':False if old else c['target_met']}


def main(job):
    result=load(job/'result.json');previous=load(ROOT/'jobs/20261022_085158/result.json')
    before=sorted([summary(c,True) for c in previous['results']],key=lambda x:x['id'])
    after=sorted([summary(c) for c in result['results']],key=lambda x:x['id'])
    records=[]
    for p in list(job.glob('*.json'))+list((job/'history').glob('*.json')):
        r=load(p)
        if isinstance(r,dict) and 'values' in r and 'solver_s' in r.get('timings',{}):records.append((p,r))
    assert all(abs(v*10-round(v*10))<1e-7 for _,r in records for v in r.get('geometry_mm',{}).values())
    assert all(abs(r['design']['wire_diameter_mm']*10-round(r['design']['wire_diameter_mm']*10))<1e-7 for _,r in records)
    solver_s=sum(r['timings']['solver_s'] for _,r in records)
    precise=[r['timings']['solver_s'] for _,r in records if r.get('resolution_points',60)>=120]
    coarse=[r['timings']['solver_s'] for _,r in records if r.get('resolution_points',60)<120]
    counts=load(job/'evaluation_count_audit.json')
    rounds=[load(p) for p in sorted(job.glob('optimization_round*.json'))]
    evaluations=sum(x['evaluations'] for x in rounds)
    unique=counts['unique_combinations_across_rounds'];full=counts['theoretical_grid_combinations']
    previous_opt=load(job/'prior_optimization_session.json')['optimization_compute_s']
    interrupted_opt=load(job/'pre_equal_torque_result.json')['timings']['optimization_compute_s']
    opt_s=sum(x['optimization_compute_s'] for x in rounds)
    wall=result['timings']['cumulative_program_wall_s']
    comparison=[]
    for c in result['results']:
        pre=load(job/(c['pre_detail_label']+'.json'))
        p=c['prediction'];v=pre['values']
        comparison.append({'id':c['id'],'prediction_scope':'Initial proportional geometry before detailed review',
            'predicted_efficiency_pct':p['efficiency_pct'],'FEA_efficiency_pct':v['System Efficiency'],
            'efficiency_error_percentage_points':v['System Efficiency']-p['efficiency_pct'],
            'predicted_torque_Nm':result['request']['operating_point']['torque_Nm']*1.01,
            'FEA_torque_Nm':v['Shaft Torque'],'predicted_phase_R_ohm':p['resistance_ohm'],
            'FEA_phase_R_ohm':v['Phase Resistance'],
            'predicted_terminal_rms_V':p['terminal_line_rms_V'],'FEA_terminal_rms_V':v['Line-Line Terminal Voltage (rms)'],
            'predicted_iron_B_T':None,'predicted_torque_ripple_pct':None})
    sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
             ['design_job.py','optimize_low_voltage.py','low_voltage.py','dimension_grid.py','detailed_review.py','flux_limits.py']}
    evidence={'request':result['request'],'before':before,'after':after,'prediction_comparison':comparison,
              'counts':{'global_variables':4,'additional_directed_shape_parameters':3,'simultaneous_7_variable_optimization':False,
                  'full_global_grid':full,'arithmetic_evaluations_one_pass':evaluations,'unique_global_combinations':unique,
                  'reduction_pct':100*(1-unique/full),'arithmetic_evaluations_including_two_resumes':evaluations*3,
                  'successful_MotorCAD_records':len(records),'failed_attempts_before_saved_result':2,
                  'total_MotorCAD_attempts':len(records)+2,
                  'detailed_shape_alternatives':sum(len(c['detailed_review_trials']) for c in result['results'])},
              'timings':{'latest_arithmetic_search_s':opt_s,'all_three_arithmetic_search_sessions_s':previous_opt+interrupted_opt+opt_s,
                  'successful_recorded_solver_s':solver_s,'coarse_solver_median_s':statistics.median(coarse),
                  'precision_solver_median_s':statistics.median(precise),'cumulative_program_wall_s':wall,
                  'wall_scope':'Includes setup, failed attempts, repeated precision evaluations and resume launches; excludes editing gaps and report creation.'},
              'source_sha256':sources,'all_generated_geometry_inputs_on_0_1_mm_grid':True}
    out=ROOT.parent/'outputs'/f'grid_review_{job.name}';out.mkdir(exist_ok=True)
    (out/'comparison.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 0.1 mm 치수 기반 0.5 N·m 초기 설계 재검토','',
      '## 판단','',
      '**새 요구조건 전체를 만족하는 모델은 확보하지 못했다.** 효율·토크 개선과 별도로 최대 B·토크 리플 조건을 만족해야 한다. PWM 전류 리플은 여전히 미검증이다. 이번 결과는 제조 확정용이 아니다.','',
      '## 요구조건과 실행 범위','',
      '- 0.5 N·m 이상, 3,500 rpm, DC 9/12/16 V, 효율 88% 이상, 20°C.',
      '- POSCO 50PN470, JL MAG N48UH, Radial 형상·Radial 착자, Delta, 1가닥·1병렬.',
      '- FOC Id=0/SVPWM, 10 kHz, 4극·12슬롯. 최대 B 1.8 T, 토크 리플 최대 20%, PWM 전류 리플 상한 15%.',
      '- 기본 치수 4개는 SciPy 차분진화로 탐색. 이후 슬롯 깊이·치 폭·자석 극호 3개 변경 항목을 조합한 상세 대안 3개/모델을 해석했다.',
      '- 7변수를 동시에 최적화하거나 검증된 상세 형상 대리모델을 학습한 것은 아니다. 공극·자석 두께 등은 이번 상세 단계에서 독립 탐색하지 않았다.',
      '- 입력 형상·도체 치수는 0.1 mm 간격. 각도는 mm 대상이 아니며, 계산으로 얻는 권선 길이·재질 데이터는 강제 반올림하지 않는다.',
      '- 절연 포함 선경은 기존 최소 여유 0.07 mm를 보존하도록 0.1 mm 단위로 올림. 실제 생산선경/절연 규격은 별도 확정이 필요하다.','',
      '## 이전/새 결과 비교','',
      '모두 20°C·12 V·3,500 rpm 해석값. 적층 길이는 철심 길이이며 전체 모터 축방향 길이가 아니다. 이전과 새 모델 ID는 각 탐색 내부 식별자로, 동일 모델의 전후 변경을 뜻하지 않는다.','',
      '| 구분 | 모델 | 철심 외경 mm | 하우징 외경 mm | 적층 mm | 축토크 N·m | 효율 % | Motor-CAD Kt N·m/A선첨두 |',
      '|---|---|---:|---:|---:|---:|---:|---:|']
    for group,rows in [('이전',before),('새 결과',after)]:
        for r in rows:lines.append(f"| {group} | {r['id']} | {r['stator_od_mm']:.3f} | {r['housing_od_mm']:.3f} | {r['stack_mm']:.3f} | {r['torque_Nm']:.5f} | {r['efficiency_pct']:.3f} | {r['Kt_MotorCAD_Nm_per_A_line_peak']:.5f} |")
    lines+=['','Kt는 BPM 전자기 출력의 공극 평균 FE 토크/선전류 첨두 기준이다. Lab 출력의 Kt 정의와 혼용하지 않는다. 축토크/상 RMS, 축토크/선 RMS 비도 comparison.json에 별도로 저장했다. 이는 해당 운전점의 비이며 미분 토크상수는 아니다.',
      '[Motor-CAD BPM Kt 정의](https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/drive_bpm_output_data.html)','',
      '## 새 결과 요구조건 판정','',
      '| 모델 | 토크 리플 % / 상한 20 | 철심 최대 B T / 상한 1.8 | 상저항 Ω | Ld / Lq mH | 전체 목표 |','|---|---:|---:|---:|---:|---|']
    for r in after:lines.append(f"| {r['id']} | {r['ripple_pct']:.3f} | {r['max_iron_B_T']:.3f} | {r['phase_R_ohm']:.5f} | {r['Ld_mH']:.5f} / {r['Lq_mH']:.5f} | 미달·PWM 미검증 |")
    lines+=['','## 수식 예측과 Motor-CAD 비교','',
      '초기 비례 형상 단계의 예측과 같은 단계의 FEA를 비교한다. 상세 형상이 바뀐 후의 결과를 이전 형상 예측과 직접 오차 비교하지 않는다. 최종 형상의 B·리플을 예측하는 수식 모델은 아직 없다.','',
      '| 모델 | 수식 효율 % | 초기 FEA 효율 % | 차이 %p | 수식 상저항 Ω | 초기 FEA 상저항 Ω |','|---|---:|---:|---:|---:|---:|']
    for r in comparison:lines.append(f"| {r['id']} | {r['predicted_efficiency_pct']:.3f} | {r['FEA_efficiency_pct']:.3f} | {r['efficiency_error_percentage_points']:+.3f} | {r['predicted_phase_R_ohm']:.5f} | {r['FEA_phase_R_ohm']:.5f} |")
    lines+=['','## 변수·조합·실제 계산 수','',
      '| 기본 변수 | 범위 | 선택 수 |','|---|---|---:|','| 철심 외경 | 55.0~100.0 mm, 0.1 mm 간격 | 451 |',
      '| 적층 길이 | 20.0~65.0 mm, 0.1 mm 간격 | 451 |','| 코일 턴 수 | 1~8, 정수 | 8 |','| 구리 선경 | 0.8~2.2 mm, 0.1 mm 간격 | 15 |','',
      f'- 기본 변수 전체 직교 조합: 451 × 451 × 8 × 15 = **{full:,}개**. 형상/성능 탈락을 제거하기 전 숫자다.',
      f'- 2회 탐색의 수식 평가 호출: **{evaluations:,}회**, 중복 제외 치수 조합 **{unique:,}개**. 전체 조합 대비 검토 조합 감소율 **{100*(1-unique/full):.5f}%**.',
      f'- 장애 복구 및 같은 부하 비교를 위한 재개에서 같은 탐색을 두 번 더 실행했다. 이를 포함한 수식 평가 호출은 **{evaluations*3:,}회**. 고유 조합은 여전히 {unique:,}개다. 집계 확인용 별도 재현 계산은 이 숫자와 시간에서 제외했다.',
      '- 추가 상세 변경 항목 3개: 슬롯 깊이, 치 폭, 자석 극호. 고정된 3개 대안/모델, 총 9개 대안을 비교했다. 7차원 전체 격자 크기나 전체 상세 최적화 감소율로 위 숫자를 해석하면 안 된다.',
      f'- 저장된 성공 Motor-CAD 해석 **{len(records)}회**, 저장 전 실패/검사 중단 **2회**, 실제 시도 합계 **{len(records)+2}회**. 전류 조정·전압 변경·정밀도 변경·재평가를 포함한다.',
      '- 이 계산 횟수 감소가 전역 최적해 보장이나 모든 가능성 검토를 의미하지 않는다.','',
      '## 실측 시간','',
      f'- 마지막 2회 수식 탐색: **{opt_s:.3f}초**. 최초 측정은 1.192초였으며, 재개 반복까지 수식 탐색 누적 **{previous_opt+interrupted_opt+opt_s:.3f}초**.',
      f'- 성공한 Motor-CAD 순수 솔버 시간 합계: **{solver_s:.1f}초 ({solver_s/60:.2f}분)**. 실패한 호출의 순수 솔버 시간은 분리 기록되지 않아 제외했다.',
      f'- 기본 해석 중앙값: **{statistics.median(coarse):.1f}초/회**, 정밀 해석 중앙값: **{statistics.median(precise):.1f}초/회**.',
      f'- 실제 Python 작업 실행 누적: **{wall:.1f}초 ({wall/60:.2f}분)**. 앱 기동·재질 준비·입출력·장애·전류 재조정·재평가 포함. 코드 편집 대기와 보고서 작성 시간은 제외했다.',
      '- 이번 시간은 제한된 상세 후보 검토의 실측이며, 전체 상세 형상 대리모델 최적화·열 연성·PWM 회로 검증 완료 시간은 아니다.','',
      '## 남은 검증','',
      '- 코깅 단독·전류각/전류 크기 스윕·권선표 대조·메시 수렴을 아직 완료하지 않았다. 리플 원인을 확정할 수 없다.',
      '- 철손 데이터는 50/60 Hz 기반이며, 4극 3,500 rpm의 116.7 Hz 해석은 해당 주파수 범위를 벗어난다.',
      '- 20°C 지정 전자기 해석이며 열 평형·냉각·감자·기계 강도·실제 인버터/PWM·Delta 순환전류는 미검증이다.',
      '- 전압 검사는 지정 전류 파형을 유지하는 데 필요한 전압 검사이며 실제 구동 회로 검증을 대신하지 않는다.',
      '- 이전 결과도 새 B/리플 조건으로는 합격 모델이 아니다. 새 결과와 이전 결과의 목표 만족 표시는 같은 새 기준으로 읽어야 한다.','',
      '## 산출물','',f'- 원본 작업: `{job}`',
      '- comparison.json: 숫자·정의·횟수·시간·코드 SHA-256.',
      '- 원본 작업 폴더 inputs.csv/results.csv/motorcad.csv 및 .mot 파일에서 입력·판정·상세 해석 결과 확인 가능.']
    (out/'INITIAL_DESIGN_REVIEW_KO.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(out),'after':after,'counts':evidence['counts'],'timings':evidence['timings']},ensure_ascii=False,indent=2))


if __name__=='__main__':main(Path(sys.argv[1]))
