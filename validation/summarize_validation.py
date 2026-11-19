from pathlib import Path
import csv,json,math
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'run_20261021_400V'
report=json.loads((OUT/'report.json').read_text(encoding='utf-8'))
if report['status']!='solved':raise RuntimeError('All three solver runs must succeed')
summaries=[];checks=[]
def compare(temp,name,calc,reference,basis):
 err=abs(calc-reference)/max(abs(reference),1e-12)*100
 checks.append(dict(temperature_C=temp,name=name,calculated=calc,motorcad=reference,error_pct=err,basis=basis))
for scenario in report['scenarios']:
 t=scenario['temperature_C'];p=OUT/f'results_{t}C.csv'
 content=p.read_text(encoding='cp1252',errors='replace')
 values={}
 for row in csv.reader(content.splitlines(),delimiter=';'):
  if len(row)<2:continue
  try:values.setdefault(row[0],float(row[1]))
  except ValueError:pass
 def v(key):return values[key]
 outside='Operating point outside voltage limit' in content
 if outside:raise RuntimeError(f'{t}C exceeds voltage limit')
 speed=v('Shaft Speed');omega=speed*math.pi/30
 R=v('Phase Resistance');irms=v('Phase Current (rms)');ipeak=v('Phase Current (peak)')
 rho=v('Armature Conductor Resistivity');mlt=v('Armature Conductor MLT')*.001
 n=v('Armature Turns per Phase');area=v('Armature Turn CSA')*1e-6
 compare(t,'상 저항 ρ×MLT×N/A',rho*mlt*n/area,R,'Motor-CAD에서 산출한 MLT·단면적을 사용한 일관성 검사')
 compare(t,'동손 3×Irms²×R',3*irms**2*R,v('Armature DC Copper Loss (on load)'),'Motor-CAD 전류·저항 기반 일관성 검사')
 compare(t,'축 출력 T×ω',v('Shaft Torque')*omega,v('Output Power'),'단위·출력 정의 검사')
 compare(t,'전력 수지 Pout+loss',v('Output Power')+v('Total Losses (on load)'),v('Input Power'),'전력 수지 검사')
 compare(t,'효율 Pout/Pin',100*v('Output Power')/v('Input Power'),v('System Efficiency'),'효율 정의 검사')
 compare(t,'dq 토크 1.5×p×ψd×Iq',1.5*3*v('Flux linkage D (On load)')*.001*ipeak,v('Average torque (DQ)'),'Motor-CAD 쇄교자속 사용, Id=0; 독립 자속 예측 검증 아님')
 compare(t,'Kt(첨두 전류 기준)×Ipeak',v('Torque Constant (Kt)')*ipeak,v('Average torque (MsVw)'),'Motor-CAD Kt는 이 모델에서 상 첨두전류 기준')
 compare(t,'Ke(선간 기본파 첨두)×ω',v('Back EMF Constant (Ke) (fundamental)')*omega,v('Back EMF Line-Line Voltage (peak) (fundamental)'),'CSV 반올림 영향 포함; 선간 전체 RMS와 구분')
 br=1.105*(1-.0012*(t-20))
 compare(t,'Br 선형 온도 보정',br,v('Magnet Br (Used)'),'예제 자석의 αBr=-0.12%/°C 가정; 제조사 다온도 곡선 검증 아님')
 summaries.append(dict(temperature_C=t,phase_resistance_ohm=R,back_emf_LL_rms_total_V=v('Back EMF Line-Line Voltage (rms)'),back_emf_LL_rms_fundamental_V=v('Back EMF Line-Line Voltage (peak) (fundamental)')/math.sqrt(2),shaft_torque_Nm=v('Shaft Torque'),shaft_power_W=v('Output Power'),system_efficiency_pct=v('System Efficiency'),total_loss_W=v('Total Losses (on load)'),dc_copper_loss_W=v('Armature DC Copper Loss (on load)'),Ld_mH=v('D Axis Inductance'),Lq_mH=v('Q Axis Inductance'),voltage_limit_exceeded=outside))
data=dict(model=report['geometry'],settings=report['settings'],summaries=summaries,checks=checks,limitations=['Template derivative, not optimized or independently sized from targets','Generic template materials; not JL MAG/POSCO qualification','20/60/100 C are prescribed uniform component temperatures, not a thermal solution','Higher-temperature magnet values use a linear coefficient, not measured multi-temperature curves','Consistency checks partly reuse Motor-CAD geometry/flux/results; independent analytical electromagnetic prediction is not validated','Single current angle and speed, no mesh/time-step convergence study, demagnetization or 6-step verification'])
(OUT/'comparison.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 검증용 모터 PyMotorCAD 1차 실행 결과','', '상태: 20·60·100°C 전자기 해석 완료. 400 V 운전점에서 전압 한계 초과 표시는 없음.','', '## 모델과 실행 범위','', '- 설치 예제 Electromagnetic_Model.mot에서 파생한 6극·18슬롯 SPM. 독립 신규 최적화 설계는 아님.', '- 고정자 외경 130 mm, 적층/자석 길이 75 mm, 공극 1 mm, 자석 두께 4 mm.', '- 40 turn/coil, 240 turn/phase, Y결선, 상 전류 5 Apeak(3.5355 Arms), 1,500 rpm, 위상전진각 0°.', '- 초기 300 V 시도는 전압 한계 초과로 탈락. 최종 검증 조건은 400 V. 초기 결과는 별도 보존.', '- 재질은 원본 예제의 일반 재질을 유지. JL MAG/POSCO 적용 검증은 별도 필요.','', '## 온도별 Motor-CAD 결과','', '|온도 °C|상 저항 Ω|역기전력 선간 기본파 Vrms|축 토크 N·m|축 출력 W|시스템 효율 %|총 손실 W|','|---:|---:|---:|---:|---:|---:|---:|']
for s in summaries:lines.append('|'+ '|'.join(f'{s[k]:.4f}' for k in ['temperature_C','phase_resistance_ohm','back_emf_LL_rms_fundamental_V','shaft_torque_Nm','shaft_power_W','system_efficiency_pct','total_loss_W'])+'|')
lines+=['','## 수식 대조','', '아래는 기본 수식 및 정의의 일관성 검사다. 저항 계산의 MLT·단면적과 토크 계산의 쇄교자속 등 일부 입력을 Motor-CAD에서 사용했다. 따라서 독립 초기설계 계산기의 예측 정확도가 검증된 것은 아니다. CSV는 표시 자릿수로 반올림되어 있다.','', '|검사|3개 온도 중 최대 상대 차이 %|','|---|---:|']
for name in dict.fromkeys(c['name'] for c in checks):lines.append(f"|{name}|{max(c['error_pct'] for c in checks if c['name']==name):.5f}|")
lines+=['','## 중요한 발견 및 한계','', '- Motor-CAD의 Kt는 이 예제에서 상 첨두전류 기준이다. UI의 Arms 기준 값으로 표시하려면 √2 배 변환이 필요하다.', '- Motor-CAD 기본파 Ke는 이 예제에서 선간 첨두전압/기계 각속도 기준이다. 선간 RMS·krpm 기준으로 명시적으로 변환해야 한다.', '- 전체 RMS와 기본파 RMS는 고조파 때문에 다르다. 비교 표에는 기본파 RMS를 사용했다.', '- 20/60/100°C는 권선·자석·철심에 지정한 온도다. 주위 온도를 입력해 열평형을 계산한 결과가 아니다.', '- 예제 자석의 Br은 -0.12%/°C 선형 보정이다. 온도별 실측곡선과 감자 검증은 완료되지 않았다.', '- Ld/Lq는 출력에 존재하지만 별도 인덕턴스 성능 시험은 비활성화했다. 해당 값의 별도 수렴성 검증은 수행하지 않았다.', '- 망·시간 간격 수렴성, 6 STEP, 감자, 기계 강도, 제어기 손실 모델과 연속 정격은 검증 범위 밖이다.', '- 결과의 시스템 효율 표기는 Motor-CAD 출력 명칭을 유지했다. 제품의 모터 효율/인버터 포함 효율 매핑은 추가 확인이 필요하다.','', '## 파일','', '- validation_20C.mot / validation_60C.mot / validation_100C.mot: 실제 해석 모델', '- results_20C.csv / results_60C.csv / results_100C.csv: Motor-CAD 원본 결과', '- comparison.json: 구조화 비교값 및 수식 오차', '- report.json: 실행 로그와 API 원값','']
(OUT/'검증결과.md').write_text('\n'.join(lines),encoding='utf-8')
print(json.dumps({'summaries':summaries,'max_check_difference_pct':max(c['error_pct'] for c in checks)},ensure_ascii=False,indent=2))
