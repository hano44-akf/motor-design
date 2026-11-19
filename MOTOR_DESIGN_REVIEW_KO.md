# 자동차용 모터 초기 설계 프로그램 — 독립 검토용 설계안

작성일: 2026-10-19 / 설계안 버전: 0.3

Claude 검토 반영: 역기전력 부호, 축방향 길이 제한, FEMM 기준각·병렬 경로 정의를 보완했다. 철손 모델 등의 채택 조건과 검토문 오류는 `CLAUDE_REVIEW_RESPONSE_KO.md`에 기록했다. 구현 완료를 의미하지 않는다.

이 문서는 구현 완료 보고서가 아니다. 확정 요구사항, 구현 제안, 미검증 모델과 검토 질문을 구분한다. Claude 등 다른 검토자가 이 문서만 읽고 수식·물리·구조·개발 범위를 평가할 수 있도록 작성했다.

## 1. 목적과 현재 상태

사용자는 모터 설계·해석·제작·시험 담당자다. 요구 운전점을 만족하는 초기 설계 후보를 빠르게 탐색하고, FEMM 및 상용 전자계 도구로 정밀도를 높이는 로컬 Windows 프로그램을 원한다.

목표 흐름:

`요구조건 → 유효 형상·권선 후보 → 간이 전자계·다중 운전점 평가 → DOE·다목적 탐색 → 후보 선택·변수 고정 → FEMM 평가·국소 개선 → 실제 제조사 재질 확정 → Motor-CAD/Maxwell 출력 → 추가 해석·시험`

현재 실제 구현된 것은 재질 데이터 추출·보존·검사 도구다. 모터 형상 생성기, 설계 엔진, 최적화, FEMM 자동화, 사용자 화면, 상용 모터 모델 출력은 아직 구현 전이다.

- 일반 MDB 원시 데이터 취합 및 파일/필드 보존 검사 수행.
- 사용자가 제공한 Neodymium_magnet.gdb의 637개 재질을 공식 API로 추출 완료. B–H 46,652점 확보.
- 추가 4개 DB의 543개 목록은 별도 추출 작업 진행 중. 이 문서는 추가 작업의 완료를 전제하지 않는다.
- 전체 Granta 재질을 모두 확보했다는 의미는 아니다. 입력 목록 범위와 실제 성공 목록을 기록한다.
- 과거 Inset 한 사례에서 약 7.5% 차이가 있었다는 이야기는 재현 검증 전이다. 정확도 보증이나 일괄 보정계수로 사용하지 않는다.

## 2. 확정 요구사항과 제안

### 확정된 방향

- 최초 대상: 내전형 SPM, 3상 정현파 FOC, Id=0.
- Motor-CAD/Maxwell 목표 버전: 2026 R1. Motor-CAD·Granta 라이선스 보유.
- 다중 운전점, 운전점별 전압·온도·전류 한계, 필수 운전점 전부 만족 여부 평가.
- 모터 단독 효율. 인버터 손실은 모터 효율에서 제외하고 DC 전류 계산에는 별도 반영.
- 권선·자석 온도는 입력값. 열·구조해석과 연속정격 시간 예측은 초기 제외.
- 원형선, 선경·병렬 가닥·병렬 회로·점적률·전류밀도 제약.
- 1차 탐색부터 최적화. DOE와 최적화 목적을 구분.
- 일부 변수를 고정하고 재탐색. 기존 치수를 직접 입력하는 평가 모드.
- 결과에서 출처·가정·미계산·미지원·실패를 구분. 미계산을 0으로 채우지 않는다.

### 구현 제안 — 확정 사양으로 오해하지 말 것

- 첫 형상: 일정 두께 원호형 표면 자석, 방사 방향 자화, 단일 슬롯 템플릿.
- 첫 자석 축방향 길이는 적층 길이와 동일하게 제한. 길이가 다를 때 생기는 축방향 프린징은 단순 2D 슬라이스로 재현할 수 없다. 후속 지원은 3D 해석 또는 검증된 보정 모델로 평가한다.
- 첫 권선: 지정된 극슬롯·코일 피치·층수의 검증된 템플릿 목록. 임의 극슬롯 자동 권선 합성은 후속 기능.
- Y를 먼저 검증하고 Δ의 평형 기본파 모델을 추가. Δ 순환 고조파 전류는 초기 제외.
- 첫 운전 영역: 정방향 모터링. 발전·회생·약계자·고장/단락 해석은 별도 확장.
- Python 계산 엔진 + PySide6 로컬 데스크톱 UI 제안. 최종 UI 선택은 엔진 규격 확정 후 가능.
- 대표 재질 탐색을 기본으로 하되 실제 제조사 재질을 직접 탐색하는 모드도 허용.

### 초기 제외 기능

PWM 고조파 손실, 정밀 AC 동손, 자석·도전성 슬리브 와전류손, 비가역 감자, 복잡한 스큐, 3D 엔드 효과, 열평형, 구조 강도, 소음·진동, 고장 과도. 제외된 손실이 있는 효율은 명시된 손실 범위의 추정값이다.

## 3. 사용자 입력과 자동값 정책

요구 입력:

- DC 최소/정격/최대 전압 및 운전점별 실제 적용 전압.
- 속도, 요구 축토크, 최소 모터 효율, 필수/선택 운전점 구분.
- 최대 철심 외경·적층 길이. 선택적으로 축경·내경·공극·자석 두께 등.
- 선전류 RMS/Peak, DC 평균전류, 도체 RMS 전류밀도 한계.
- 구리 점적률/피복 포함 점적률, 라이너·슬롯 웨지·최소 절연 간격.
- 극수·슬롯수·권선 방식·결선·턴수·병렬 회로·가닥수·선경 후보.
- 철심·자석 후보, 권선·자석 온도, 철손용 철심 온도/측정 온도 정책.
- 기계손실 곡선 또는 명시적 가정. 전압 변조 방식·이용률·인버터 손실 정책.

변수는 `fixed / range / choices / auto`를 갖는다. 자동 범위도 유한해야 하며 실제 적용 범위와 근거를 결과에 기록한다.

공란은 의미를 구분한다:

1. 선택적 제한 공란 → 해당 사용자 제한 없음. 물리·제조 제약은 유지.
2. 설계변수 자동 → 검증된 템플릿 범위에서 자동 결정.
3. 필수 물성 공란 → 해당 계산 불가. 0 대입 금지.

DC 최소/최대가 입력되어도 모든 극단 온도·전압의 조합을 자동 생성하지 않는다. 사용자가 지정한 시나리오를 평가하고, 견고성 검토 시나리오를 추가한 경우 별도로 표시한다.

## 4. 단위와 전기적 관례

### 공통 기준

- 내부: m, kg, s, A, V, Ω, H, Wb, T, A/m, W, N·m, rad.
- 온도: 저장 기준을 K로 통일하는 안. UI와 재질 원문 °C는 입력/출력 경계에서 변환하며 원문도 보존. 온도차의 K와 °C 수치는 같다.
- 속도 입력 rpm, 내부 기계각속도 ωm=2πn/60.
- 극수 P, 극쌍수 p=P/2, 슬롯수 Qs. 전기각 θe=pθm+θ0, ωe=pωm, f=pn/60.
- 전압·전류 결과마다 선간/권선상, RMS/Peak, 기본파/전체파형을 기록.
- 초기 정현파 가정에서 Peak=√2 RMS. 고조파 포함 파형에는 이 관계를 적용하지 않는다.

### dq 정의

상순서 a-b-c, d축을 회전자 PM 기본파 자속 방향, 양의 q전류가 양의 토크를 만드는 진폭 불변 Park 변환:

```text
xd = (2/3)[xa cosθe + xb cos(θe−2π/3) + xc cos(θe+2π/3)]
xq = −(2/3)[xa sinθe + xb sin(θe−2π/3) + xc sin(θe+2π/3)]
```

평형 기본파에서 dq 전류 크기는 권선상 Peak다. 기본 전력식은 `P=3/2(vd id+vq iq)`다. 전력 불변 Park 변환과 계수를 섞으면 안 된다.

여기서 권선상은 Y에서 상-중성점 가지, Δ에서는 삼각형 한 변의 가지를 뜻한다. Δ의 선전류 좌표계와 권선상 좌표계에는 결선 방향에 따른 위상차가 있으므로 실제 연결 행렬로 변환한다.

### 결선 관계 — 평형 기본파 한정

| 관계 | Y | Δ |
|---|---|---|
| 선전류 IL,rms | Iph,rms | √3 Iph,rms |
| 선간전압 VLL,rms | √3 Vph,rms | Vph,rms |
| 단자 DC 저항 RLL | 2Rph | 2Rph/3 |

저항 관계는 균형 잡힌 동일 상저항·정지 DC 측정·외부 회로 분리 조건이다. 같은 저항 관계를 결합 인덕턴스 측정에 그대로 적용하면 안 된다.

Δ에서 Ia=Iab−Ica 등 실제 KCL 연결을 사용하고, 기본파의 √3 관계와 위상까지 테스트한다. 고조파 순환전류·불균형·병렬 경로 순환전류는 이 간소화의 범위 밖이다.

## 5. 형상·권선 모델

### 형상 데이터

```text
SPMGeometry
  template_id, template_version
  stator_outer_diameter, stator_bore_diameter, stack_length
  airgap, shaft_diameter, rotor_backiron_geometry
  magnet_thickness, pole_arc_ratio, magnet_length
  slot_opening, tooth_tip, slot_depth, tooth_width, fillets
  insulation, slot_liner, wedge
  magnetization_pattern
```

치수에서 재현할 수 있는 방향 있는 경계·영역·재질 할당을 공통 형상 출력에 포함한다.

기하 검사: 영역 겹침/음의 면적/공극 폐쇄/자석 간섭/치·요크 최소두께/도체 슬롯 수용/코일 피치·병렬 경로 실현 가능성. 첫 버전은 공극을 유효 공극으로 바꾸는 계수와 실제 기하 공극을 구분한다.

철심 체적은 실제 철심 영역×적층 길이×적층률로 계산한다. 외형 원통 체적과 순철 체적은 별도 지표다. 원호형 자석의 총 체적은 전체 극호 점유율 αp에 대해 `Vmag=αp π(ro²−ri²) lmag`이며 실제 템플릿 적분값과 검산한다.

### 권선 데이터

슬롯/층별 coil side의 상, 방향, 코일 ID, 턴수, 병렬 경로 ID를 명시한다. 코일의 직렬 순서와 연결 노드도 저장한다. 총 슬롯 도체 수만으로 권선을 정의하지 않는다.

`q=Qs/(2pm)`, m=3은 분포를 설명하는 지표다. q가 정수가 아니라는 이유로 무효 판정을 하지 않는다.

상 기본파 권선계수는 실제 부호 있는 도체 분포의 복소 합으로 계산:

`kw,ν = |Σc sc Nc exp(jνpθc)| / Σc |Nc|`

θc는 기계각, sc는 coil-side 방향이다. 경로별로 계산하고 각 병렬 경로의 유기전압 크기·위상 일치를 검사한다. 단순 분포계수×단절계수 식은 정형 권선의 교차검산에 사용한다.

Nseries는 한 병렬 경로의 직렬 턴수다. 전체 도체 수·코일 턴수·상 직렬 턴수·가닥수·병렬 회로 수를 독립 개념으로 저장한다.

### 저항·전류밀도·점적률

구리 소선 직경 dcu, 병렬 가닥수 ns, 균등 병렬 경로 수 a:

```text
Astrand = π dcu² / 4
ρ(T) = ρref [1 + αρ(T−Tref)]
Rpath = ρ(T) lpath / (ns Astrand)
Rph = Rpath / a           # 경로가 동일할 때만
Istrand,rms = Iph,rms / (a ns)
Jrms = Istrand,rms / Astrand
Pcu = 3 Iph,rms² Rph
```

일반 연결은 각 도체의 `Σ Ibranch² Rbranch`로 검산한다. 경로별 저항이 다르면 균등 분배를 가정하지 않는다.

lpath에는 슬롯 내 양쪽 활성 도체, 엔드턴, 필요 시 리드선이 포함된다. `lpath=Nseries·평균턴길이+리드선길이`는 동일 코일 템플릿일 때의 근사다. 엔드턴 길이 모델 출처를 저장한다.

`fill_copper=슬롯 내 구리 단면 합/정의된 슬롯 기준 면적`

`fill_insulated=피복 포함 도체 단면 합/같은 기준 면적`

분모가 전체 슬롯인지 라이너 등을 뺀 사용 가능 면적인지 명시한다. 점적률 통과는 제조 가능성의 충분조건이 아니다. 배열·슬롯 입구·굽힘·절연 제약을 별도로 검사한다.

## 6. 1차 전자계 계산

### 6.1 자석·공극 자기회로

아래는 방사자화 SPM의 무부하 근사 출발점이며 Inset/IPM에 재사용하지 않는다.

```text
Hm lm + Bg geff/μ0 + Σj Hfe,j(Bj) lj = 0
Bm = Br(Tm) + μ0 μrec Hm        # 국소 선형 리코일 근사일 때
Φm = Bm Am
Φg = Bg Ag
Φm = Φg + Φleak
```

철심 포화·누설·면적차를 무시한 단순 검산식은 `Bg≈Br lm/(lm+μrec geff)`다. 이를 완성 엔진의 보편식으로 사용하지 않는다.

실제 엔진은 자석·공극·치·요크의 비선형 회로를 반복 수렴시킨다. 슬롯팅에 대한 Carter 보정 등은 해당 슬롯 템플릿에서 선정·검증하며, 임의 상수 보정을 전체 범위에 적용하지 않는다. 누설과 프린징은 독립 경로/면적 또는 검증된 계수로 처리하고 중복 반영하지 않는다.

온도별 감자곡선이 있으면 선형 Br·μr 상수보다 곡선을 우선한다. 사용 중인 B–H가 정상 B–H인지 intrinsic J–H인지 구분하며 `J=B−μ0H`를 사용한다. μrec와 B/H로 얻은 원점 기준 투자율을 혼동하지 않는다.

곡선 온도·H 범위 밖 외삽은 기본 금지. 양쪽 온도의 공통 H 범위에서 B(H,T)를 보간하는 방식은 제안이며, knee 부근 정확도와 물리적 일관성을 검토해야 한다. 비가역 감자 예측을 지원한다는 뜻은 아니다.

### 6.2 기본파 자속·쇄교자속·역기전력

공극 B 분포를 계산하고 공간 Fourier 기본파를 추출한다. 이상적 직사각형 극호 분포의 검산식은 `B1,peak=(4/π) Bplateau sin(παp/2)`다. 슬롯팅·프린징이 있는 실제 파형에 이 식을 그대로 대입하지 않는다.

기본파가 `B(θm)=B1,peak cos(pθm)`인 경우:

```text
Φ1 = 2 B1,peak rg leff / p
ψm = Nseries kw,1 Φ1
Eph,peak = ωe ψm
Eph,rms = ωe ψm / √2 = 4.44288 f Nseries kw,1 Φ1
```

Φ1은 기본파 한 극을 적분한 자속이고, 평균 공극 B×자석 면적과 혼용하지 않는다. ψm은 권선상 기본파 PM 쇄교자속 Peak다. 가능하면 실제 권선함수와 공간 B를 직접 적분한 결과로 검산한다.

### 6.3 인덕턴스

첫 후보식: 에너지/자기회로 기반 자화 인덕턴스 + 슬롯·치끝·엔드턴 누설.

계수·자속 경로·권선 정규화가 검증되기 전에는 정량 정확도를 보장하지 않는다. SPM이어도 슬롯팅·포화 때문에 Ld=Lq가 정확히 성립하지 않을 수 있다. 임시로 동일하다고 두면 결과에 가정으로 표시한다.

자석 쇄교자속을 포함한 `ψd/id`를 Ld로 정의하지 않는다. secant, incremental, apparent 인덕턴스를 별도 정의한다. 입력된 L을 쓰는 임시 평가와 형상에서 L을 예측하는 기능도 구분한다.

## 7. 운전점·제어·전력수지

### 7.1 철손을 생략한 기본 dq 기준 모델

다음은 정상상태의 기본 관계이며 저항은 실제 권선상 등가 저항이다.

```text
ψd = ψm + Ld id
ψq = Lq iq
vd = Rph id − ωe ψq
vq = Rph iq + ωe ψd
Te = (3/2) p (ψd iq − ψq id)
   = (3/2) p [ψm iq + (Ld−Lq) id iq]
```

Id=0일 때 `Te=1.5pψm iq`, `Iph,rms=|iq|/√2`, `Vph,peak=√(vd²+vq²)`다. 포화가 크면 L·ψ를 상수로 두지 않고 상태 의존 모델을 사용한다. 출처: 표준 PMSM dq 모델의 관례와 비교할 수 있는 [MathWorks 모델 설명](https://www.mathworks.com/help/mcb/ref/surfacemountpmsm.html). 이 문서의 결선·손실 처리 세부는 별도의 제안이다.

### 7.2 Kt·Ke 기준

철손 전류를 생략하고 Id=0인 기본 모델에서:

```text
Kt,phase_peak = 1.5 p ψm
Kt,line_rms,Y = 3/√2 p ψm
Kt,line_rms,Δ = √(3/2) p ψm
Ke,LL_rms,Y [V/(rad/s mechanical)] = √(3/2) p ψm
Ke,LL_rms,Δ [V/(rad/s mechanical)] = p ψm/√2
```

따라서 이 특정 정의에서는 `Kt,line_rms = √3 Ke,LL_rms`다. 단위가 SI라는 이유만으로 임의 정의의 Kt=Ke를 적용하지 않는다. krpm당 Ke는 기계 rad/s 기준값에 `1000·2π/60`을 곱한다. 고조파가 있으면 선간 기본파와 전체 파형 Ke도 분리한다.

### 7.3 인버터 전압 한계

기본 2레벨 인버터의 선형 변조 영역에서 상-가상중성점 기본파 Peak 한계:

- SPWM: Vdc/2
- SVPWM: Vdc/√3

이를 선간 RMS로 환산하면 SPWM은 `√3/(2√2) Vdc`, SVPWM은 `Vdc/√2`다. 이용률 u≤1과 소자·데드타임의 전압 여유 ΔVLL,rms를 적용:

`VLL,rms,available = max(0, u kmod Vdc − ΔVLL,rms)`

dq가 요구하는 권선상 전압을 결선별 선간전압으로 변환해서 비교한다. Y용 상전압 한계를 Δ 권선상 전압에 그대로 적용하면 안 된다. R·I 전압강하가 dq 전압식에 포함되어 있으므로 인버터 한계에서 권선 저항강하를 다시 빼지 않는다. 전압 이용률은 효율과 별개다.

기본파 상전압 기준은 [MathWorks PWM 설명](https://www.mathworks.com/help/simscape-electrical/ref/pwmgeneratorthreephasethreelevel.html)과 대조하되, 위 이용률·여유량 정책은 프로그램의 제안 규격이다.

Id=0에서 전압 한계를 넘으면 불합격이다. 자동으로 음의 Id나 과변조를 사용하지 않는다.

### 7.4 손실과 축토크 — 반드시 독립 검토할 부분

정방향 모터링에서:

```text
Pshaft = Tshaft ωm
Pmotor,in = Pshaft + Pcu + Pfe + Pmech + Pother
ηmotor = Pshaft / Pmotor,in
Pdc = Pmotor,in + Pinverter
Idc,average = Pdc / Vdc
```

DC 평균전류는 선전류와 다르며, DC 리플 RMS/Peak 제한은 초기 모델의 지원 범위가 아니다. ηinverter를 입력할 경우 `Pdc=Pmotor,in/ηinverter`; 별도의 동일 인버터 손실과 중복 계산하지 않는다.

기계손실은 측정 곡선 우선. 필요 시 `Pmech(n)` 경험 모델을 쓰되 계수 출처를 명시한다. 정지점에서는 P/ω를 계산하지 않는다. 정지 마찰·요구 토크를 직접 다루고 효율은 정의 불가 또는 목적상 평가 제외로 처리한다.

**핵심 문제:** 철손을 효율 분모에만 더하면 에너지 기반 입력전력과 dq의 `1.5(vd id+vq iq)`가 달라진다. 전류·전압 한계 근처에서는 이 차이를 숨기면 안 된다.

검토할 모델 수준(아래 모델들을 같은 운전점에 중복 적용하지 않음):

1. `loss_postprocess`: 철손 전류를 무시한 dq 전자계 추정 + 별도 손실 후처리. 빠르지만 단자 전력 일치 오차를 표시하고, 전류·전압 최종 합격 판정에 제한을 둔다. 이를 완전히 일관된 최종 회로 해로 표시하지 않는다.
2. `core_loss_branch`: 등가 철손 분기를 포함한 정상상태 회로. 우선 구현 후보이지만 아래 모델의 정의와 검증 필요.
3. `loss_torque`: 초기 탐색용 등가 손실토크 근사 후보. 양의 속도·모터링·Id=0·등방성 SPM 범위에서 `Te,req=Tshaft+(Pmech+Pfe)/ωm`, `iq=Te,req/(1.5 p ψm)`를 사용한다. 이때 dq 전력수지는 닫히지만, 실제 철손 전류의 위상과 단자 전압 정확도를 검증한 것은 아니다. 결과는 `estimated`로 표시하고 Rc 모델·기준 해석과 비교한다. 반복 횟수를 2~3회로 고정하지 않고 잔차·상태변화 허용오차와 최대 반복수를 둔다. 정지점에서 P/ω를 사용하지 않으며 PWM 손실까지 무조건 0으로 처리하지 않는다. 보수적 오차 방향을 일반적으로 보장하지 않는다.

등가 철손 분기 모델 제안:

```text
i = im + ic                      # 권선 단자 전류 = 자화 전류 + 철손 분기 전류
ud = −ωe ψq,  uq = ωe ψd          # 정상상태 내부 유기전압
ic,d = ud/Rc,  ic,q = uq/Rc
vd = Rph id + ud,  vq = Rph iq + uq
ψd = ψm + Ld im,d,  ψq = Lq im,q
Pfe = (3/2)(ud²+uq²)/Rc
Te = (3/2)p(ψd im,q − ψq im,d)
Te = Tshaft + Tmech              # 이 등가회로 안에서
```

여기서는 **제어기의 Id=0은 단자 id=0**이다. im,d=0과 같지 않다. 상태별 Pfe로 Rc를 맞추고 iq·자화전류·자속을 함께 풀어 전력 일치를 검사한다. Pfe=0이면 분기를 제거하고 정지점은 별도 식으로 처리한다.

이 분기는 분포 철손·고조파·PM 회전손실을 완벽히 재현하는 모델이 아니다. 정자계 FEMM의 전류·토크와 연결할 때 무엇이 자화전류인지 정의하고, 철손을 다시 Te−Pfe/ω 형태로 중복 차감하지 않는다. 직접 손실 저항토크로 처리하는 대안은 별도 토크 정의와 회로 유도가 필요하다.

위 분기 예제의 Ld/Lq는 자화 분기의 인덕턴스다. 슬롯·엔드턴 누설을 포함한 전체 인덕턴스를 무조건 이 위치에 넣지 않는다. 등방성 직렬 누설 Lσ를 별도로 두면 `vd=Rph id−ωe Lσ iq+ud`, `vq=Rph iq+ωe Lσ id+uq`가 된다. 직렬 누설의 정상상태 평균 실전력은 0이며, 전체 L의 자화/누설 분리와 FEMM 값 연결은 검토 과제다.

### 7.5 철손 모델

우선 재질의 특정손실 표 `pfe(Bpeak,f,T)`를 사용해 치·요크 등의 국부 자속 추정치로 적분한다.

`Pfe=Σregion pfe(Bpeak,region, f, Tfe) · mregion`

specific loss 단위가 W/kg인지 volumetric W/m³인지 확인한다. 원본 필드명이 LossDensity라는 이유만으로 단위를 추정하지 않는다.

Steinmetz형 `p=k f^α B^β` 또는 분리형 `p=kh f B^α + ke f² B² + kex(fB)^1.5`는 선택적 피팅 모델이다. 계수 단위·자속 Peak/RMS·주파수·온도·적용 범위를 함께 저장한다. Motor-CAD 계수를 다른 정의의 식에 무조건 대입하지 않는다.

사인파 단축 측정 곡선을 회전자 좌표계의 회전자 철손, 회전자계·고조파·minor loop 손실에 그대로 적용하지 않는다. 초기에는 고정자 기본파 철손 근사 범위를 표시하고, 손실 항목마다 계산·생략·입력 부족 상태를 둔다.

## 8. FEMM 평가 엔진

초기 기준 백엔드는 FEMM 4.2의 22Oct2023 빌드와 공식 배포 pyFEMM 0.1.4 조합을 목표로 한다. 실제 설치·연결 호환성 검증 전에는 작동 확인 상태로 표시하지 않는다. FEMM 5의 06Oct2026 빌드는 공식 배포가 확인되었으며 후속 비교 대상으로 둔다. 버전별 통신을 어댑터로 분리하고 실행파일 해시·바인딩 버전·설정을 결과에 저장한다. 공식 안내의 3~5배 속도 개선은 우리 모터 모델의 보장값이 아니다. 출처: [4.2 공식 배포](https://www.femm.info/doku/doku.php?id=download), [5 공식 배포](https://femm.info/doku/doku.php?id=download5).

Incremental permeability의 동작점 미분 응답과 frozen permeability의 포화 투자율 고정 재해석을 구분한다. 각 기능의 설치 빌드 지원·API·sliding band 조합을 개별 시험한다.

### 자동 생성

공통 형상에서 2D planar 모델, 깊이, 재질, 자화 방향, 권선 circuit, mesh, 외곽 경계를 만든다. 첫 검증은 전체 360° 모델. 대칭 섹터는 극슬롯·권선·자화·부하의 대칭성을 입증한 후 적용한다.

가동 회전자 처리는 공식 sliding-band 방법을 우선 검토한다. 자석 및 철심 길이가 다르면 단순히 모델 깊이를 한 길이로 설정해 해결할 수 없다. 공식 근거: [FEMM Sliding Band](https://www.femm.info/doku/doku.php?id=SlidingBand), [FEMM 문서·pyFEMM 매뉴얼](https://www.femm.info/doku/doku.php?id=Documentation).

### 무부하

1. Ia=Ib=Ic=0.
2. 기계각 위치를 샘플링하며 상 쇄교자속 λa,b,c(θm) 계산.
3. 수동 부호 관례의 모터 단자식 `v=Ri+dλ/dt`에 맞춰 `e_back=+ωm dλ/dθm`로 역기전력을 복원한다. circuit 방향을 일치시킨다. Fourier 미분은 기계각 h차에 `j h ωm`, 전기각 k차에 `j k ωe`를 적용한다. 충분한 각도 샘플과 수렴 검사는 별도로 필요하다.
4. 주기 파형을 Fourier 분석해 기본파·THD 분리. 미분 잡음과 aliasing 검사.
5. 선간 전압은 실제 상 전압 차/결선으로 계산. Δ의 개방 가지 EMF와 닫힌 Δ 무부하를 혼동하지 않는다.

### 부하

무부하 기본파를 `λa=ψm cos(pθm+φa)`로 정의하고 `θ0=φa`로 기준각을 고정한다. 상순서와 회전 방향을 함께 저장하고 abc/dq 부호를 시험한다. 쇄교자속의 기본파 RMS 크기만 비교해서는 부호 오류를 찾을 수 없다.

병렬 경로는 실제 코일표로 정의한다. 모든 경로를 가상 직렬 circuit으로 묶고 `Iph/a`를 인가한 모델에서만, 동일 경로 대칭을 전제로 반환 쇄교자속을 a로 나눈다. 실제 경로별 circuit 결과에 다시 a를 나누지 않는다. 동일 코일들을 직렬에서 두 병렬 경로로 재결선하면 경로 직렬턴수와 상 쇄교자속은 절반, 상 저항은 1/4이며 같은 토크의 단자전류는 2배가 된다(균등 분담·동일 온도 조건).

회전자 각도에 따라 dq 전류를 abc로 변환하여 정자계 스냅숏을 푼다. 회전자만 움직이고 abc 전류를 고정하면 동기 정상상태 토크 파형이 아니다.

평균토크, peak-to-peak, RMS ripple을 계산하며 `% ripple=(Tmax−Tmin)/|Tavg|·100`의 정의를 표시한다. Tavg가 0에 가까우면 %는 정의 불가로 두고 절대 N·m 값을 사용한다.

코깅은 무전류의 별도 해석이다. 이상적 주기 후보 `2π/lcm(P,Qs)`는 템플릿 대칭을 확인한 경우만 사용한다. 샘플 간격·범위는 관심 고조파와 수렴 결과로 정한다.

### 인덕턴스

운전점·회전자 각도를 고정한 소전류 섭동으로:

`Linc,ij = ∂ψi/∂ij ≈ [ψi(i+δej)−ψi(i−δej)]/(2δ)`

dq 행렬의 대각·교차항을 보존한다. 섭동 크기에 대한 수렴을 확인한다. 선형/보존 모델에서 reciprocity도 검사하되, 비선형 동작점·수치 오차와 비교한다. 자석 성분 제거 방식과 secant와의 차이를 명시한다.

2D FEMM에서 얻는 저항·인덕턴스에 엔드턴 보정을 추가할 경우 출처를 기록하고 이중 반영을 방지한다. 정자계 FEMM만으로 전체 손실·실제 효율이 자동 계산됐다고 표시하지 않는다.

### 수치 검증

메시 크기, 공극 분할, 외곽 경계 거리, 회전각 간격, 토크 적분 방법을 변화시켜 수렴을 평가한다. 평균토크와 작은 코깅토크에 같은 상대 오차 조건을 사용하지 않는다.

## 9. 재질 라이브러리와 대표 재질

### 계층

1. 원본 보관: 공식 추출 MDB 및 원본 GDB를 SHA-256 기준으로 무손실 압축·중복 제거.
2. 정규화 데이터: 단위·온도·곡선 종류·측정 방향·주파수·판두께·출처·원본 해시.
3. 대표 재질: 초기 탐색용 소수 재질과 선정 근거·적용 범위·편차.

일반 N35와 N35SH를 합치지 않는다. 상온 Br 등급과 보자력/온도 특성을 별개 축으로 다룬다. 대표 재질 후보는 N30/N35/N40/N45 등 실제 확보된 등급·온도·곡선 완전성에 따라 선정한다. grade 이름만으로 온도 성능을 보증하지 않는다.

대표 선정의 기본안은 여러 곡선 평균이 아니라 **실제 재질 하나를 대표로 선택하는 medoid 방식**이다. 온도별 Br·곡선 모양·보자력 관련 지표·데이터 품질을 정규화한 거리로 비교한다. 아직 거리식·가중치는 미정이다.

상·하한 검토도 가능한 실제 재질들을 시나리오로 평가한다. 서로 다른 제조사에서 최악 속성을 각각 뽑아 만든 조합은 실재하지 않을 수 있으므로 별도 가상 경계 모델로 표시한다.

철심 대표 선정은 판두께·B–H·주파수별 철손 범위가 함께 필요하다. 압연 방향, RD/TD, 측정 주파수가 다른 B–H 데이터를 섞지 않는다. 소재 cost를 입력받지 않았다면 질량을 비용이라고 부르지 않는다.

### 저장 용량 절감

원시 JSON의 같은 필드/배열 중복을 없애고 SQLite에 단일 기준 데이터를 저장한다. 원본 bytes와 원문 수치 문자열은 압축 보관, 계산에는 검증된 float64를 사용한다. '무손실'은 원본 복원 및 원문 값 보존에 대해 주장하고, decimal→binary64를 수학적으로 정확한 변환이라고 주장하지 않는다.

CSV/전체 JSON은 필요 시 생성한다. 원본/이전 결과 삭제는 별도 사용자 승인 후 수행한다. 아직 현재 파일의 압축·DB 전환은 실행하지 않았다.

### Motor-CAD 재질 복원

공식 import/export API로 원본 MDB를 복원·가져온다. 동일 이름 충돌 시 작업 DB에서 값 비교 후 버전별 재질명을 분리하며 기존 사용자 DB를 덮어쓰지 않는다.

원본 ZIP 복원 해시 일치와 Motor-CAD 가져오기→재내보내기 물성 일치는 다른 검증이다. 파생 계수가 재계산될 수 있으므로 의미 단위 비교를 한다. Granta 암호화 원본과의 완전 일치까지 확인된 것은 아니다.

대표가 실제 재질 참조이면 해당 원본을 출력한다. 가상 평균 재질이면 custom material로 내보내고 실제 제조사 원본으로 표기하지 않는다.

공식 API 근거: [export_solid_material](https://motorcad.docs.pyansys.com/version/stable/methods/_autosummary_Materials/ansys.motorcad.core.motorcad_methods.MotorCAD.export_solid_material.html), [Materials API](https://motorcad.docs.pyansys.com/version/stable/methods/_autogen_Materials.html).

## 10. 프로그램 구성

```text
motor_design/
  domain/           # 데이터·단위·전기적 관례·상태·검증
  geometry/         # 템플릿·영역·권선·제조 제약
  evaluation/
    analytical/     # 비선형 자기회로·자속·인덕턴스 추정
    circuit/        # 결선·dq·전압한계·운전점 해 찾기
    losses/         # 구리·철심·기계·인버터
    constraints/    # 공통 합격/불합격/판정불가
  search/           # DOE·혼합변수 탐색·Pareto·재탐색
  adapters/
    femm/
    motorcad/
    maxwell/
  materials/        # catalog·원본 보관·대표 재질 참조
  app/              # CLI·UI·실행 작업관리·저장·보고
tests/
examples/
```

단일 Python 패키지와 로컬 프로세스로 시작한다. 초기부터 마이크로서비스를 만들지 않는다. UI는 계산 라이브러리를 호출하며, 계산 엔진이 UI 위젯이나 전역 상태를 참조하지 않는다.

제안 라이브러리: NumPy/SciPy 수치 계산, Pydantic 계열 데이터 검증 또는 dataclass+명시적 validator, pymoo 혼합 다목적 탐색, PySide6 UI, SQLite 실행/재질 카탈로그. 실제 버전은 설치 호환성 검증 후 고정한다. FEMM·Motor-CAD를 각각 단일 작업 worker로 시작하고 라이선스·동시실행 검증 후 확장한다.

## 11. 데이터 규격과 엔진 인터페이스

```python
class ElectromagneticBackend(Protocol):
    def capabilities(self) -> CapabilitySet: ...
    def prepare(self, design: ResolvedDesign, settings: EMSettings) -> ModelHandle: ...
    def characterize(self, model: ModelHandle, request: EMRequest) -> EMResult: ...

class OperatingPointEvaluator(Protocol):
    def evaluate(self, design: ResolvedDesign, point: OperatingPoint,
                 em: EMResult, losses: LossModel,
                 settings: CircuitSettings) -> OperatingPointResult: ...

def evaluate_candidate(design, points, backend, settings) -> EvaluationResult: ...
```

공통 요청은 동일 규격이지만 엔진의 capabilities는 다르다. 간이 엔진이 토크 리플을 지원하지 않으면 null/unsupported를 반환한다. FEMM 실패를 간이 값으로 조용히 대체하지 않는다.

```text
Project: schema_version, project_id, requirements, search_space, preferences
ResolvedDesign: geometry, winding, material_refs, resolved_auto_values, hashes
OperatingPoint: id, speed, shaft_torque, voltage, temperatures, limits, required
EMResult: flux_model, torque_model, inductance_definition, waveforms, provenance
Metric: value|null, unit, basis, method, status, assumptions, valid_range
ConstraintResult: actual, limit, physical_margin, normalized_violation, decision
RunManifest: input_hash, code_version, material_hashes, solver_versions, settings,
             seed, parent_run, timestamps, artifact_paths, warnings/errors
```

계산 결과 상태와 설계 합격 판정은 별도 축으로 관리한다.

- 계산 상태: computed / estimated / missing_input / unsupported / failed / out_of_domain.
- 판정: pass / fail / indeterminate.
- FEMM 계산 결과라고 실험 검증된 값은 아니다. 검증 수준도 별도 필드로 둔다.

파일 저장 제안:

```text
project/
  project.json
  materials.sqlite
  materials_raw/<sha256>.zip
  runs/<run_id>/manifest.json
  runs/<run_id>/results.json
  runs/<run_id>/waveforms/
  runs/<run_id>/solver_files/
  runs/<run_id>/logs/
```

첫 구현은 JSON+실행 폴더로 시작하고 SQLite를 추가해도 된다. 단위 포함 입력을 정규화한 뒤 canonical hash를 계산한다. 재질·엔진·손실모델·메시·회전각·온도가 달라지면 캐시를 재사용하지 않는다. float의 허용오차로 다른 설계를 무작정 같은 캐시 키로 합치지 않는다.

작업 상태: queued → running → completed/failed/cancelled. 진행률은 해석 케이스/각도 기준으로 제공. 부분 산출물은 보존하고 결과 파일은 원자적으로 저장한다. 취소 시 사용자 소유의 Motor-CAD 프로세스를 종료하지 않는다.

## 12. DOE·최적화·다중 운전점

### 설계변수

- 연속: 내경·공극·적층 길이·극호비·자석 두께 등.
- 정수: 턴수·가닥수·병렬 회로 등.
- 선택형: 검증된 극슬롯·권선 템플릿, 선경, 재질, 결선.
- 조건부: 특정 템플릿에서만 의미가 있는 변수.

권선·형상 유효성 → 저비용 평가 → 필수 운전점 해 찾기 → 제약 판정 → 목적함수 순서로 평가한다. 무효 형상을 solver에 보내지 않는다.

### 목적함수 제안

- 최소화: 필수 운전점 중 최대 손실비 또는 최저 효율의 음수.
- 최소화: 정의된 철심 체적/외형 envelope.
- 최소화: 자석 질량.

목적함수는 처음에 2~3개로 제한. 가중 평균 효율은 운전 시간/에너지 가중치가 제공된 경우만 사용한다. 비용 데이터 없이는 비용 최적화라고 표기하지 않는다. 단일 순위의 임의 가중치를 숨기지 않고 Pareto 후보를 표시한다.

제약을 `g≤0`로 표현:

```text
gI,k = (IL,k − IL,max,k)/Iscale,k
gV,k = (VLL,k − VLL,available,k)/Vscale,k
gη,k = (ηmin,k − ηk)/ηscale,k
```

정규화 스케일은 양수이고 문서화한다. 사용자에는 실제 단위 여유량을 함께 표시한다. 입력 부족 제약은 통과로 간주하지 않는다. 최악 운전점과 전체 운전점별 결과를 보존한다.

### 탐색 방법

1. 유효한 discrete template 선택.
2. 템플릿별 연속 공간에서 DOE: Latin hypercube 등.
3. 간이 엔진 다목적 탐색: NSGA-II 계열 + 혼합변수 연산자.
4. 중복 제거·실현 가능성·비지배 필터.
5. 사용자가 후보/변수를 고정.
6. FEMM은 소수 후보부터 비용 측정 후 국소 탐색. 필요하면 surrogate/trust region 도입.

pymoo는 `MixedVariableProblem`과 혼합변수 처리를 제공하지만 모터의 유효 형상·권선을 생성해주지는 않는다. 혼합변수 GA를 기본값 그대로 실행하면 다목적 NSGA-II가 된다고 가정하지 않는다. [혼합변수 공식 문서](https://pymoo.org/customization/mixed.html), [제약 정의](https://www.pymoo.org/getting_started/part_2.html).

초기 예산 제안: 간이 계산 유효 후보 2,000~10,000개부터 시간 측정, FEMM 후보 10~30개부터 시작. 후보 수와 각도별 solve 수를 구분한다. 종료는 최대 시간·solve 예산·실현 가능 Pareto 개선 정체를 함께 사용한다. 전역 최적해를 보장한다고 표시하지 않는다.

DOE의 상관분석을 원인 효과나 전역 민감도로 단정하지 않는다. 범위·조건부 변수·불합격 제거로 생긴 선택 편향을 표시한다. Sobol 등 방법은 변수 독립성·샘플링 조건이 맞을 때만 도입한다.

## 13. 사용자 화면

1. 프로젝트/요구조건: 운전점 표, 전압·전류 기준, 치수 제한, 자동값 표시.
2. 형상/권선: 단면도, 슬롯층별 상·방향, 코일 연결, 실현 불가 원인.
3. 재질: 대표/실제 구분, 온도별 곡선, 출처, 추정 물성 표시, 적용범위.
4. 탐색: 고정/범위/후보/자동, DOE/최적화, 예산·시드·중지/재개.
5. 후보 비교: Pareto 산점도, 요구조건별 여유량, 최악 운전점, 비교표.
6. FEMM: 진행률, 메시·각도 설정, 자속밀도·쇄교자속·토크 파형, 수렴 결과.
7. Export: 실제 재질과 템플릿 대응 확인, 지원 범위, 생성 스크립트·모델·로그.

상태 표현 예: '간이 추정', 'FEMM 계산', '입력 부족', '온도 범위 밖', '검증 모델 없음'. '효율 0%'로 미계산을 표현하지 않는다.

## 14. Motor-CAD/Maxwell 출력

### Motor-CAD

검증된 기준 .mot 템플릿 + 변수/재질/권선 매핑 스크립트부터 시작한다. 임의 FEMM 형상을 자동으로 Motor-CAD 표준 템플릿으로 바꿀 수 있다고 가정하지 않는다. Adaptive Geometry 지원은 별도 개발 항목이다.

새 인스턴스에서 작업 DB 사본 선택 → 원본 재질 복원/import → 치수·권선·결선·온도 설정 → 저장 → 재열기 → 값 대조 → 기준 해석 실행 → 출력 검증 순으로 완료 판정한다.

### Maxwell

PyAEDT 기반 Maxwell 2D 생성 스크립트: 영역·재질·자화·권선·병렬 경로·경계·motion band·깊이·mesh·setup·report. geometry만 생성하고 완전한 해석 모델이라고 표시하지 않는다. [Maxwell2d 공식 API](https://aedt.docs.pyansys.com/version/stable/API/_autosummary/ansys.aedt.core.maxwell.Maxwell2d.html).

비교는 같은 형상·재질 곡선·온도·전류·각도·깊이·엔드 보정 조건으로 한다. Maxwell transient와 FEMM magnetostatic의 손실/고조파 차이를 단순 수치오차로 취급하지 않는다.

## 15. 테스트와 완료 기준

### 필수 수학·회로 테스트

- 단위 변환 round-trip, rpm↔rad/s, 선간/상, RMS/Peak.
- Park 변환·역변환과 abc/dq 전력 일치.
- Y/Δ 연결 행렬과 √3 관계, 동일 가지 전류에서 동손·토크 일치.
- 코일 병렬화 시 경로 전류·저항·동손 일치.
- 전압 경계 직전/초과, DC 평균전류 제한, 0속도 분기.
- 실패·누락·범위 밖 결과가 합격으로 처리되지 않는지.
- 철손 분기 도입 시 전력수지 잔차와 해 수렴.

숫자 검산 사례 — 철손 0, 선형 Y, 외부 보정 없음:

```text
p=4, ψm=0.02 Wb, Rph=0.1 Ω, Ld=Lq=0.001 H
id=0, iq=10 A_peak, ωm=100 rad/s
ωe=400 rad/s
vd=−4 V_peak, vq=9 V_peak
Vph,peak=√97=9.84886 V
Iph,rms=7.07107 A
Te=1.2 N·m
Pcu=15 W, Teωm=120 W
Pmotor,in=1.5·9·10=135 W
Pmech=5 W → Pshaft=115 W, Tshaft=1.15 N·m
ηmotor=115/135=85.1852%
Vdc=24 V, Pinverter=0 → Idc,average=5.625 A
```

이 숫자 예제는 실제 모터가 아니라 단위·전력수지 테스트용이다.

순수 수식 테스트의 허용오차는 double 정밀도 수준으로 설정할 수 있지만 solver 수렴과 실험 정확도 기준을 동일하게 두지 않는다.

### 검증 계층

1. 코드/단위의 정확성.
2. 자기회로·형상·권선의 해석적 기준 사례.
3. FEMM 메시·각도·경계 수렴.
4. 동일 조건 Motor-CAD/Maxwell 교차 비교.
5. 실제 시험과 비교.

상용 FEA와 일치해도 시험 정확도가 보장되는 것은 아니다. 초기 정확도 목표값은 기준 사례를 얻은 뒤 정한다. 예컨대 Ke/평균토크 상대오차와 효율 percentage-point 오차는 구분하고 저토크/코깅은 절대 오차도 사용한다.

형상·온도·전류별 여러 기준 모델을 선정하고 보정용/독립 검증용을 분리한다. 설계 범위를 벗어난 후보는 검증 범위 밖으로 표시한다. 데이터가 없으면 숫자 신뢰구간을 임의 생성하지 않는다.

## 16. 개발 단계와 통과 조건

| 단계 | 실제 산출물 | 통과 조건 |
|---|---|---|
| 0 | 재질 원본·목록·곡선·출처 | 이름·해시·필드·배열 일치, 누락 상태 명확 |
| 1 | 도메인·단위·결선·기본 dq | 수학·전력 검산 사례 통과 |
| 2 | 단일 SPM 형상·권선·직접 평가 | 기준 도면·코일표·저항·체적 대조 |
| 3 | 비선형 자기회로·손실·다중 운전점 | 수렴/입력 부족/전압·전류 제약 판정 |
| 4 | 후보 생성·DOE·Pareto·UI | 재현 가능한 탐색, 변수 고정·저장·재개 |
| 5 | FEMM 자동화·비교 | 무부하/부하/수렴 검증, 손실 후처리 출처 |
| 6 | 실제 재질 재평가·상용 출력 | 2026 R1 재열기·입력 대조·해석 성공 |
| 7 | 검증 범위 확장·정확도 개선 | 독립 모델 및 시험 기반 오차 관리 |

첫 사용자 버전은 1~5를 한 템플릿으로 연결하는 것을 목표로 한다. 6은 템플릿 하나씩 추가한다. 정확도 개선을 기다리며 전체 개발을 중단하지 않되, 미검증 결과를 확정 설계로 표시하지 않는다.

단계 3~4에서 수동 기준 설계 1~2개의 FEMM 360° 비교를 병행 작업으로 계획한다. 목적은 간이 모델의 자속·인덕턴스 편향 조기 발견이며, 해당 사례만으로 전체 최적화 영역의 정확도를 인증하지 않는다. 초기 최적화는 그대로 유지한다.

## 17. Claude에게 특별히 요청할 검토

우선순위 높은 항목:

1. dq 정규화·부호·Y/Δ·Kt/Ke·인버터 전압 한계가 서로 일관적인가?
2. Id=0은 단자전류 기준인데 철손 분기를 포함한 자화전류와 어떤 관계인가? 제안된 등가회로와 Te·축토크·Pfe 연결에 잘못된 가정이 있는가?
3. 철손 후처리만 사용하는 빠른 모델의 사용 범위와 제약 판정 정책은 적절한가?
4. SPM 비선형 자기회로에서 슬롯팅·누설·포화·자석 recoil을 최소 비용으로 구현하는 구체적인 회로와 수식은 무엇인가?
5. 인덕턴스 근사가 첫 엔진의 전압 판정에서 병목이 되지 않는가? 초기에는 측정/FEA 보간을 일부 허용해야 하는가?
6. 대표 재질의 실제 medoid 선정과 온도 보간 방법은 물리적으로 적절한가? 더 나은 기준이 있는가?
7. 자석 길이와 적층 길이가 다른 경우의 2D 슬라이스 모델을 언제 도입해야 하는가?
8. 엔드턴·병렬 경로·권선계수·점적률·선경의 정의가 실제 제조와 일치하는가?
9. 정자계 FEMM의 토크·쇄교자속·미분 인덕턴스·철손 후처리에서 누락되는 필수 물리가 무엇인가?
10. 단일 템플릿 MVP에 제안 구조가 과도한가? 더 작은 실제 동작 버전을 제안할 수 있는가?
11. 혼합변수·조건부변수·형상 복구가 탐색 편향을 만들지 않는가? FEMM 예산에 적절한 국소 최적화 방식은 무엇인가?
12. 원본 재질 복원과 상용 출력에서 파일 동일성/물성 의미 동일성/성능 동일성을 어떻게 분리해 검증해야 하는가?

추가로 검토할 사항:

- 회전자 슬리브·접착층이 유효 공극과 손실에 주는 영향. 초기 제외 또는 입력 제약 중 어떤 것이 적절한가?
- 권선 불균형, 병렬 경로 유기전압 차이, Δ triplen 순환전류를 감지만이라도 해야 하는가?
- 철손 자료의 판두께·방향·열처리·시험 조건, 펀칭/조립 스트레스 보정의 취급.
- 자석 공차·공극 공차·온도·전압 편차를 다루는 최소 견고성 평가.
- 고정자 외경·적층 길이만 만족한 모터를 패키지 크기까지 만족했다고 오해하지 않도록 하는 방법.
- optimization이 모델의 근사 오류를 악용해 경계의 비현실적 후보를 고르는 문제와 방지책.
- 음수/0 토크, 낮은 속도, 무부하, 데이터 범위 밖, 수치 실패 등 경계 조건.
- 소프트웨어 버전 고정, 중단/재개, 라이선스 실패, 원본 DB 보호, 회귀 검증 세트.

## 18. 그대로 전달할 검토 요청문

> 첨부된 자동차용 SPM 초기 설계 프로그램 설계안을 전기기기·전자계 해석·수치해석·소프트웨어 관점에서 독립 검토해 주세요. 아직 구현 전 제안이 많으며 기존 AI의 수식과 구조가 맞다고 전제하지 마세요. 특히 dq/결선/전압 한계/철손 분기/축토크/전력수지의 일관성을 수식으로 확인해 주세요. 오류는 '원문 주장 → 문제 → 수정식/대안 → 최소 재현 테스트' 형식으로 지적해 주세요. 확정 요구사항을 임의로 확장하지 말고, 필수 수정과 후속 개선을 분리해 주세요. 미확인 API는 공식 출처로 확인하거나 미확인으로 남겨 주세요. 마지막에는 (1) 개발 전 반드시 해결할 문제, (2) 구현하면서 검증할 문제, (3) 최소 실제 동작 버전, (4) 가장 먼저 만들 테스트 10개를 제안해 주세요. 정확도 수치나 라이브러리 기능을 근거 없이 보장하지 마세요.

## 19. 출처와 적용 범위

공식 문서는 표준 관계·API 기능의 확인에 사용했다. 본 문서의 시스템 구조, 재질 선정, 손실 모델 결합, 개발 순서는 프로젝트 제안이며 해당 문서가 전체 설계안을 보증하는 것은 아니다.

- PMSM dq 기준: https://www.mathworks.com/help/mcb/ref/surfacemountpmsm.html
- PWM 기본파 전압: https://www.mathworks.com/help/simscape-electrical/ref/pwmgeneratorthreephasethreelevel.html
- FEMM 자료: https://www.femm.info/doku/doku.php?id=Documentation
- Sliding Band: https://www.femm.info/doku/doku.php?id=SlidingBand
- PyMotorCAD API: https://motorcad.docs.pyansys.com/version/stable/methods/index.html
- Material export: https://motorcad.docs.pyansys.com/version/stable/methods/_autosummary_Materials/ansys.motorcad.core.motorcad_methods.MotorCAD.export_solid_material.html
- PyAEDT Maxwell2d: https://aedt.docs.pyansys.com/version/stable/API/_autosummary/ansys.aedt.core.maxwell.Maxwell2d.html
- pymoo 혼합변수: https://pymoo.org/customization/mixed.html
- pymoo 제약: https://www.pymoo.org/getting_started/part_2.html

stable 웹 문서는 향후 변경될 수 있다. 실제 개발에서는 설치된 패키지 버전과 해당 문서 버전을 함께 고정하고 2026 R1에서 동작 검증한다.
