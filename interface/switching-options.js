/* PWM period count is a design eligibility screen, not a PWM loss simulation. */
if(state.switchingKHz===undefined)state.switchingKHz='';
if(state.pwmCurrentRipplePct===undefined)state.pwmCurrentRipplePct='';
function effectiveCurrentRipple(){
  const value=state.pwmCurrentRipplePct;
  if(value===''||value===undefined||value===null)return 15;
  if(!Number.isFinite(Number(value))||Number(value)<=0)throw Error('허용 PWM 전류 리플은 양수로 입력하세요. 공란은 상 기본파 RMS 대비 15%입니다.');
  return Number(value);
}
function effectiveTorqueRipple(){
  for(const o of state.ops){
    if(o.ripple!==''&&o.ripple!==undefined&&o.ripple!==null&&(!Number.isFinite(Number(o.ripple))||Number(o.ripple)<0||Number(o.ripple)>20))throw Error('토크 리플 상한은 0~20%로 입력하세요. 공란은 20%입니다.');
  }
  const value=state.ops[0]?.ripple;
  return value===''||value===undefined||value===null?20:Number(value);
}
const fieldBeforeController=field;
field=function(label,key,unit='',value=state[key],placeholder='공란',scope='root'){
  if(key==='ripple'&&scope==='op')return fieldBeforeController(label,key,unit,value===undefined?20:value,'공란 = 20%',scope).replace('step="any"','step="any" min="0" max="20"');
  return fieldBeforeController(label,key,unit,value,placeholder,scope);
};
function switchingFrequencyHz(){
  const value=state.switchingKHz;
  if(value===''||value===undefined||value===null)return 10000;
  if(!Number.isFinite(Number(value))||Number(value)<=0)throw Error('스위칭 주파수는 양수로 입력하세요. 공란은 10 kHz입니다.');
  return Number(value)*1000;
}
function switchingPoleLimit(rpm,hz){return 2*Math.floor(60*hz/(20*rpm)+Number.EPSILON*8*Math.max(1,60*hz/(20*rpm)));}
function switchingSummary(){
  try{
    const hz=switchingFrequencyHz(),ops=state.ops.filter(o=>Number.isFinite(o.rpm)&&o.rpm>0);
    if(!ops.length)return `적용 주파수 ${(hz/1000).toLocaleString('ko-KR')} kHz · 요구 RPM 입력 후 최대 극수를 계산합니다.`;
    const rows=ops.map(o=>({rpm:o.rpm,max:switchingPoleLimit(o.rpm,hz)})),overall=Math.min(...rows.map(r=>r.max));
    return `적용 주파수 ${(hz/1000).toLocaleString('ko-KR')} kHz · 모든 운전점 공통 최대 <b>${overall}극</b><br>`+rows.map(r=>`${esc(r.rpm)} rpm → 최대 ${r.max}극`).join('<br>')+
      (overall<2?'<br><b>허용 가능한 2극 이상 모델이 없습니다.</b>':'')+
      '<br>전기 1주기당 PWM 주기 20회 이상 · 최대 극수는 짝수로 내림. 스위칭 에지 수가 아닙니다.';
  }catch(e){return esc(e.message);}
}
function switchingPanel(withInput=false){return panel('제어기 성능 · 스위칭 주파수',
  (withInput?field('스위칭 주파수','switchingKHz','kHz',state.switchingKHz,'공란 = 10 kHz')+field('허용 PWM 전류 리플','pwmCurrentRipplePct','%',state.pwmCurrentRipplePct,'공란 = 15%')+'<p class="muted">ΔIpp / 기준 운전점 권선 상전류 기본파 RMS × 100. 공란은 15%입니다. 토크 리플과 별도 항목이며, 실제 PWM 파형 검증 전에는 미검증으로 표시합니다.</p>':'')+
  `<div id="switching-limit-summary" class="notice">${switchingSummary()}</div>`+
  '<p class="muted">f전기 = 극수 × RPM / 120, N = f스위칭 / f전기. N &lt; 20인 모델은 탐색에서 제외합니다. 6 STEP에서 PWM을 쓰는 경우에는 PWM 반송 주파수이며, 6 STEP 정류 주파수를 뜻하지 않습니다.</p>');}
const conditionsBeforeSwitching=conditions;
conditions=function(){return conditionsBeforeSwitching()+switchingPanel(true);};
const operatingBeforeSwitching=operating;
operating=function(){return operatingBeforeSwitching()+'<p class="notice">토크 리플 상한은 공란이어도 20%를 적용합니다. 더 엄격한 0~20%만 지정할 수 있으며, 초과 모델은 목표 미달로 반환합니다. PWM 전류 리플과는 다른 값입니다.</p>'+switchingPanel();};
document.addEventListener('input',()=>{const summary=$('#switching-limit-summary');if(summary)summary.innerHTML=switchingSummary();});
document.addEventListener('click',e=>{if(e.target.closest('#engine-example')){state.switchingKHz='';state.pwmCurrentRipplePct='';state.ops[0].ripple=20;persist();render();}});
const studyBeforeSwitching=toStudyRequest;
toStudyRequest=function(){
  const frequency=switchingFrequencyHz();
  const currentRipple=effectiveCurrentRipple();
  const ripple=effectiveTorqueRipple();
  const rpm=Math.max(...state.ops.map(o=>Number(o.rpm)||0));
  if(rpm>0){
    const limit=switchingPoleLimit(rpm,frequency);
    if(limit<2)throw Error('전기 1주기당 PWM 20회 조건을 만족하는 극수가 없습니다.');
    if(mode('poles')==='fixed'&&state.geometry.poles>limit)throw Error(`현재 RPM·스위칭 주파수의 최대 극수는 ${limit}극입니다.`);
    if(4>limit)throw Error(`최대 ${limit}극만 허용됩니다. 현재 자동 실행기는 4극 모델이므로 실행할 수 없습니다.`);
  }
  const request=studyBeforeSwitching();request.operating_point.torque_ripple_max_pct=ripple;
  return {...request,switching_frequency_hz:frequency,pwm_current_ripple_max_pct:currentRipple};
};
const reviewBeforeSwitching=review;
review=function(){reviewBeforeSwitching();try{switchingFrequencyHz();effectiveTorqueRipple();const current=effectiveCurrentRipple();$('#reviewbody').insertAdjacentHTML('beforeend',`<p>${switchingSummary()}</p><p>토크 리플: 입력 상한 적용, 공란이면 20% 이하 필수。PWM 전류 리플: 기준 상 RMS 대비 ${esc(current)}% (파형 검증 필요).</p>`);}catch(e){$('#reviewbody').insertAdjacentHTML('beforeend',`<p class="error">${esc(e.message)}</p>`);}};
$('#review').onclick=review;
const resultsBeforeSwitching=results;
results=function(){
  let html=resultsBeforeSwitching();
  if(!realJob?.result)return html;
  const r=realJob.result,frequency=r.request.switching_frequency_hz??10000;
  const ripple=r.request.pwm_current_ripple_max_pct??15;
  html+=panel('허용 PWM 전류 리플 · 기준 상 RMS',`<p>요구 상한 ${esc(ripple)}% · 실제 PWM 전류 리플은 미검증</p><div class="scroll"><table><tr><th>모델 / 온도 / DC</th><th>기준 상 RMS [A]</th><th>허용 ΔIpp [A]</th><th>실제 ΔIpp</th></tr>${r.results.map(c=>c.runs.map(x=>{
    const rms=x.values['Phase Current (rms)'];return `<tr><td>${esc(c.id)} / ${esc(x.input_options.temperature_C)}℃ / ${esc(x.design.voltage_V)} V</td><td>${esc(rms)}</td><td>${Number.isFinite(rms)?esc((rms*ripple/100).toFixed(3)):'미계산'}</td><td>미검증</td></tr>`;
  }).join('')).join('')}</table></div><p class="muted">전류 리플의 분자는 PWM 주기 내 최대−최소(A)이고 분모는 권선 상 기본파 RMS입니다. 실제 리플을 0으로 가정하지 않습니다. 이전 작업에 이 목표가 없었다면 기존 합격 판정은 이 조건을 포함하지 않습니다.</p>`);
  html+=panel('제어기 검사 · 인덕턴스 전압 상한 참고값',`<p>저장된 작업 기준 스위칭 주파수 ${esc(frequency/1000)} kHz · 전기 1주기당 PWM 20회 이상</p><div class="scroll"><table><tr><th>모델 / 온도 / DC</th><th>PWM 주기 수</th><th>Ld / Lq [µH]</th><th>전압 기준 Lq 상한 [µH]</th></tr>${r.results.map(c=>c.runs.map(x=>{
    const n=frequency/(x.readback.Pole_Number*x.values['Shaft Speed']/120),upper=x.assessment.inductance_review?.Lq_upper_H;
    return `<tr><td>${esc(c.id)} / ${esc(x.input_options.temperature_C)}℃ / ${esc(x.design.voltage_V)} V</td><td>${esc(n.toFixed(2))}</td><td>${esc((x.values['D Axis Inductance']*1000).toFixed(2))} / ${esc((x.values['Q Axis Inductance']*1000).toFixed(2))}</td><td>${Number.isFinite(upper)?esc((upper*1e6).toFixed(2)):'미계산 / 전압 여유 없음'}</td></tr>`;
  }).join('')).join('')}</table></div><p class="muted">FOC Id=0 / SVPWM, 6% 전압 여유를 둔 기본파 전압 예산 참고값입니다. 하한은 허용 PWM 전류 리플과 실제 변조 파형이 필요합니다. Ld/Lq 운전점 값과 고주파 미분 인덕턴스는 다를 수 있습니다. 스위칭 손실·PWM 전류 파형 해석은 아직 수행하지 않습니다.</p>`);
  return html;
};
render();
const footerRule=document.querySelector('footer > .muted');
if(footerRule)footerRule.textContent='공란 기본값: 스위칭 10 kHz / PWM 전류 리플 15% / 토크 리플 20% · 기타 공란 목표 제외';
