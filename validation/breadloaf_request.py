"""Explicit binding of main UI requirements to the limited Breadloaf model."""
import math
from breadloaf_search_space import search_space


def adapt(snapshot, max_line_peak_A=40, iterations=10):
    if not isinstance(snapshot,dict):raise ValueError('Main input snapshot required')
    errors=[];deferred=[];s=snapshot
    def has(v):return v is not None and v!=''
    def number(v,label,positive=True):
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or (v<=0 if positive else v<0):
            errors.append(label+' 입력값을 확인하세요.');return None
        return v
    if s.get('core')!=['50PN470'] or s.get('grades')!=[48] or s.get('suffix')!=['UH']:
        errors.append('50PN470 / N48UH를 각각 단독 선택해야 합니다.')
    spm=s.get('spm',{})
    if spm.get('shape') not in ('Breadloaf','surface_breadloaf') or spm.get('magnetisation')!='Radial':
        errors.append('Surface Breadloaf / Radial 착자를 선택해야 합니다.')
    if s.get('connection','delta')!='delta':errors.append('현재는 Delta 결선만 지원합니다.')
    if s.get('modulation')!='SVPWM' or s.get('control')!='FOC · Id = 0':errors.append('현재는 FOC Id=0 / SVPWM만 지원합니다.')
    if any(has(s.get(k)) and s[k]!=20 for k in ('temp','tmin','tmax')):errors.append('기준·최소·최대 온도는 현재 20℃만 지원합니다.')
    if has(s.get('eta')) and s['eta']!=100:errors.append('현재 제어 효율은 100%만 지원합니다.')
    if has(s.get('mechanical')) and s['mechanical']!=0:errors.append('현재 별도 입력 기계 손실은 0 W만 지원합니다.')
    if s.get('priority') not in (None,'균형형'):errors.append('현재 Breadloaf 경로는 리플 최소화 전용입니다. 설계 우선순위는 균형형을 선택하세요.')
    unit={'mm':1,'cm':10,'m':1000}.get(s.get('units','mm'))
    if unit is None:errors.append('지원하지 않는 길이 단위입니다.');unit=1
    expected={'od':85,'length':20,'gap':.5,'magnet':2.5,'poles':4,'slots':12,'turns':6,'wire':1.8,'strands':1,'paths':1,
              'bore':52.3,'shaft':16.3,'slotDepth':8.8,'slotOpening':None,'tooth':8.1}
    modes=s.get('modes',{});geometry=s.get('geometry',{})
    space=None
    try:space=search_space(s)
    except ValueError as exc:errors.append(str(exc))
    for key in set(modes)|set(geometry):
        if key in ('slotOpening','poleArc'):continue
        mode=modes.get(key,'fixed' if has(geometry.get(key)) else 'auto')
        if mode=='auto':continue
        value=geometry.get(key)
        factor=1 if key in ('poles','slots','turns','strands','paths','poleArc') else unit
        if key not in expected or mode!='fixed' or expected.get(key) is None or not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isclose(value*factor,expected[key],abs_tol=1e-8):
            errors.append(key+': 고정 개발 템플릿과 다른 형상 고정/범위는 아직 연결되지 않았습니다.')
    for group in ('statorParameters','rotorParameters'):
        for key,value in s.get(group,{}).items():
            fields=value if group=='rotorParameters' else {key:value}
            for field,setting in fields.items():
                if group=='statorParameters' and field=='slot_opening_mm':continue
                if group=='rotorParameters' and key!='surface_breadloaf':continue
                if group=='rotorParameters' and field in ('pole_arc_ed','magnet_reduction_mm'):continue
                if isinstance(setting,dict) and setting.get('mode','auto')!='auto':errors.append(field+': 상세 치수 설정은 현재 입력 연결에서 미지원입니다.')
    for field,setting in spm.get('parameters',{}).items():
        if field not in ('pole_arc_ed','magnet_reduction_mm') and isinstance(setting,dict) and setting.get('mode','auto')!='auto':
            errors.append(field+': 현재 Breadloaf 탐색에 연결되지 않은 변수입니다.')
    pairs=s.get('poleSlotCandidates',[{'poles':4,'slots':12}])
    if pairs!=[{'poles':4,'slots':12}]:errors.append('극·슬롯 후보는 4극12슬롯 하나만 선택하세요.')
    ops=s.get('ops',[])
    if not isinstance(ops,list) or len(ops)!=1 or not isinstance(ops[0],dict):errors.append('운전점 1개만 지원합니다.');op={}
    else:op=ops[0]
    if op.get('currentControl','ID0')!='ID0' or op.get('fieldWeakening',False):errors.append('운전점은 Id=0, 약계자 금지 조건만 지원합니다.')
    torque=number(op.get('torque'),'축토크');speed=number(op.get('rpm'),'RPM')
    margin=number(s.get('margin') if has(s.get('margin')) else 0,'토크 마진',False)
    voltages=[number(op[k],k) for k in ('vmin','vrated','vmax') if has(op.get(k))]
    voltages=[v for v in voltages if v is not None]
    if not voltages:errors.append('DC 전압을 하나 이상 입력하세요.')
    for a,b in (('vmin','vrated'),('vrated','vmax'),('vmin','vmax')):
        if has(op.get(a)) and has(op.get(b)) and isinstance(op[a],(int,float)) and isinstance(op[b],(int,float)) and op[a]>op[b]:errors.append('DC 전압 최소/정격/최대 순서를 확인하세요.')
    current=number(max_line_peak_A,'선전류 첨두 한도')
    if isinstance(iterations,bool) or not isinstance(iterations,int) or not 1<=iterations<=30:errors.append('탐색 예산은 1~30세대 정수입니다.')
    targets={}
    for field,label,default in (('eff','효율',None),('density','전류밀도',None),('imax','DC 전류',None),('ripple','토크 리플',20)):
        value=op.get(field) if has(op.get(field)) else default
        targets[field]=number(value,label) if value is not None else None
    if targets['eff'] is not None and targets['eff']>100:errors.append('효율은 100% 이하입니다.')
    flux=s.get('fluxDensityMaxT') if has(s.get('fluxDensityMaxT')) else 1.8
    flux=number(flux,'최대 B')
    fsw=10000
    if has(s.get('switchingKHz')):
        khz=number(s['switchingKHz'],'스위칭 주파수')
        fsw=khz*1000 if khz else None
    fsw=number(fsw,'스위칭 주파수')
    cycles=120*fsw/(4*speed) if fsw and speed else None
    if cycles is not None and cycles<20:errors.append('전기 1주기당 PWM 횟수가 20회 미만입니다.')
    if current and targets['density']:
        # Delta, one strand/path: Iline_peak = sqrt(6) * Jphase_rms * copper area.
        current=min(current,math.sqrt(6)*targets['density']*math.pi*1.8**2/4)
    pwm=number(s['pwmCurrentRipplePct'],'PWM 전류 리플') if has(s.get('pwmCurrentRipplePct')) else 15
    shaft=torque*(1+margin/100) if torque is not None and margin is not None else None
    deferred=['축토크: 3500rpm 국소 보정 영역에서는 손실을 반영해 전류를 계산하고, 영역 밖에서는 전자기 토크 필요 하한만 적용하며 축토크 미검증으로 표시; 실제 합격은 FEA에서 판정',
              '전압·동손 효율 상한은 근사 선별에 사용, 단면 B는 오차로 인해 비교 표시만 하며 실제 효율·국부 최대 B·DC 전류는 FEA 후 판정',
              'PWM 전류 리플: 아직 미검증; 전체 설계 합격으로 표시하지 않음']
    if len(set(voltages))>1:deferred.append('복수 전압: 초기 FEA는 최소 버스 한 조건만 해석하며 나머지 전압은 미검증으로 보존')
    return {'schema':'breadloaf-main-input-contract-v1','can_search':not errors,'errors':errors,
            'target_basis':'shaft','requested_shaft_torque_Nm':shaft,
            'target_electromagnetic_torque_Nm':shaft,'max_line_peak_A':current,'iterations':iterations,
            'speed_rpm':speed,'voltages_V':sorted(set(voltages)),'temperature_C':20,
            'requirements':{'efficiency_min_pct':targets['eff'],'dc_current_max_A':targets['imax'],
                'current_density_max_A_mm2':targets['density'],'torque_ripple_max_pct':targets['ripple'],'flux_density_max_T':flux},
            'pwm_current_ripple_max_pct':pwm,
            'search_space':space,
            'applied':['요구 축토크와 토크 마진: 국소 모델 유효 영역 안에서 손실 포함 전류 결정, 밖에서는 필요 전자기 토크 하한만 적용','RPM과 최소 DC 전압을 Native 입력에 저장',
                       '선전류 첨두 한도 및 전류밀도에서 환산한 한도','리플 최소화 목적함수와 0.1 mm 치수 격자'],
            'deferred':deferred,'pwm_cycles_per_electrical_period':cycles,
            'full_requirement_optimization':False,'ui_input_snapshot':s}
