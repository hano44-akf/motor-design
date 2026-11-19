/* Per-operating-point current policy, independent gap ticks, saved .mot viewer. */
function currentPolicy(o=state.ops[state.activeOp]){
  return o.currentControl|| (state.control==='FOC · MTPA'?'MTPA':'ID0');
}
function weakeningAllowed(o=state.ops[state.activeOp]){
  return o.fieldWeakening===undefined?state.control==='FOC · 약계자':o.fieldWeakening;
}
function gapBounds(){
  const m=mode('gap'),r=state.ranges.gap||{},factor=unitChoices.length.options[state.units];
  const has=v=>v!==''&&v!==undefined&&v!==null;
  let bounds=[.4,.6];
  if(m==='fixed'&&has(state.geometry.gap))bounds=[Number(state.geometry.gap)*factor,Number(state.geometry.gap)*factor];
  if(m==='range')bounds=[has(r.min)?Number(r.min)*factor:.4,has(r.max)?Number(r.max)*factor:.6];
  if(bounds.some(v=>!Number.isFinite(v)||v<=0)||bounds[0]>bounds[1])throw Error('에어갭은 양수이며 하한 ≤ 상한이어야 합니다. 공란 기본 0.4~0.6 mm입니다.');
  if(Math.ceil(bounds[0]*10-1e-8)>Math.floor(bounds[1]*10+1e-8))throw Error('에어갭 범위에 0.1 mm 간격의 치수가 없습니다.');
  return bounds;
}
const gapGeom=geom.find(x=>x[1]==='gap');if(gapGeom)gapGeom[0]='에어갭';
const operatingBeforeCurrentPolicy=operating;
operating=function(){
  const o=state.ops[state.activeOp];
  return operatingBeforeCurrentPolicy()+panel('운전점별 FOC 전류 제어',
    `<label class="field"><span>기본 전류 제어</span><select id="op-current-control"><option value="ID0" ${currentPolicy(o)==='ID0'?'selected':''}>Id = 0</option><option value="MTPA" ${currentPolicy(o)==='MTPA'?'selected':''}>MTPA · 최소 전류</option></select><span></span></label>`+
    `<label class="checks"><span><input id="op-field-weakening" type="checkbox" ${weakeningAllowed(o)?'checked':''}>전압 부족 시 약계자 허용</span></label>`+
    '<p class="muted">수식으로 요구 토크의 전류·전류각을 계산하고 선택 제어점을 PyMotorCAD에 적용합니다. 각도 전수 스윕은 하지 않습니다. MTPA는 전류 최소화이며 전체 손실 최소화와 다릅니다. 비선형 최적성·리플·감자는 별도 검증입니다. 자동 실행은 현재 운전점 1개를 지원합니다.</p>');
};
const geometryBeforeGap=geometry;
geometry=function(){
  let html=geometryBeforeGap();
  html=html.replace(/(<select[^>]*data-mode="gap"[^>]*>)([\s\S]*?)(<\/select>)/,(_,a,b,c)=>a+b.replace('>자동</option>','>자동 · 0.4~0.6 mm</option>')+c);
  return html+panel('에어갭 기본 범위',
    '<p>위 에어갭 항목에서 <b>고정값 또는 범위</b>를 지정하세요. 자동 또는 공란은 <b>0.4~0.6 mm</b>입니다. 0.1 mm 격자로 탐색하고 선택값을 Motor-CAD 형상에 적용합니다.</p><p class="muted">표시 단위를 바꾸면 입력 치수도 변환됩니다. 기본 범위의 물리적 크기는 항상 0.4~0.6 mm입니다. 공극 변경의 초기 자속·인덕턴스 예측은 근사이며 FEA로 확인합니다.</p>');
};
const studyBeforeCurrentPolicy=toStudyRequest;
toStudyRequest=function(){
  const request=studyBeforeCurrentPolicy(),o=state.ops[0],policy=currentPolicy(o);
  request.control=policy==='MTPA'?'FOC_MTPA_SVPWM':'FOC_Id0_SVPWM';
  request.operating_point.current_control=policy;
  request.operating_point.field_weakening=!!weakeningAllowed(o);
  if(o.vrated>0)request.operating_point.nominal_voltage_V=o.vrated;
  request.airgap_bounds_mm=gapBounds();
  request.open_motorcad_after=state.openMotorcadAfter===true;
  return request;
};
const reviewBeforeCurrentPolicy=review;
review=function(){
  reviewBeforeCurrentPolicy();
  try{$('#reviewbody').insertAdjacentHTML('beforeend',`<p>에어갭 ${gapBounds().join('~')} mm · ${state.ops.map((o,i)=>`운전점 ${i+1}: ${currentPolicy(o)} / 약계자 ${weakeningAllowed(o)?'허용':'금지'}`).join(', ')}</p>`);}
  catch(e){$('#reviewbody').insertAdjacentHTML('beforeend',`<p class="error">${esc(e.message)}</p>`);}
};
$('#review').onclick=review;
const actualBeforeModelViewer=actualResults;
actualResults=function(){
  let html=actualBeforeModelViewer(),r=realJob.result;
  html+=panel('선택 설정을 Motor-CAD에서 열기',
    '<p>저장된 해석의 온도·전압·전류·전류각·에어갭 설정을 새 Motor-CAD 창에서 엽니다. 원본 결과를 보존한 검토용 .mot 복사본을 사용합니다.</p>'+
    r.results.map((c,i)=>`<div class="field"><span>${esc(c.id)}</span><select id="motorcad-condition-${i}" aria-label="${esc(c.id)} 열기 조건">${c.runs.map(x=>`<option value="${esc(x.label)}">${esc(x.verification_role??'nominal')} / ${esc(x.input_options.temperature_C)}°C / ${esc(x.design.voltage_V)} V / 에어갭 ${esc(x.geometry_mm?.Airgap??'미기록')} mm / γ ${esc(x.readback.PhaseAdvance??0)}°</option>`).join('')}</select><button data-open-motorcad="${esc(c.id)}" data-condition-index="${i}">열기</button></div>`).join('')+
    '<p id="motorcad-open-feedback" role="status">열 모델과 조건을 선택하세요.</p>');
  const rows=r.results.map(c=>c.runs.map(x=>`<tr><td>${esc(c.id)} / ${esc(x.verification_role??'nominal')} / ${esc(x.input_options.temperature_C)}°C / ${esc(x.design.voltage_V)} V</td><td>${esc(x.geometry_mm?.Airgap??'미기록')}</td><td>${esc(x.readback.PhaseAdvance??0)}</td><td>${esc(x.design.control_prediction?.policy??'ID0')}</td><td>${esc(x.design.control_prediction?.field_weakening_active?'동작':'미동작')}</td></tr>`).join('')).join('');
  html+=panel('적용 제어·에어갭',`<div class="scroll"><table><tr><th>해석 조건</th><th>에어갭 mm</th><th>전류 진각 γ°</th><th>기본 제어</th><th>약계자</th></tr>${rows}</table></div><p class="muted">기본파 dq 수식 예측과 적용값입니다. MTPA의 비선형 최적성, PWM 리플, 음의 Id 감자 검증이 완료된 것은 아닙니다. 상세 결과와 CSV에 제어 예측·실제 적용 각도를 함께 저장합니다.</p>`);
  return html;
};
engineDialog.querySelector('p').textContent='연결 범위: 50PN470 / N48UH, 4극 12슬롯, Delta, 1가닥·1병렬, FOC Id=0 또는 MTPA + 선택적 약계자 / SVPWM. 에어갭은 고정값 또는 범위를 탐색합니다.';
$('#engine-start').insertAdjacentHTML('beforebegin','<p><label><input id="open-motorcad-after" type="checkbox">해석·비교 완료 후 대표 모델을 Motor-CAD에서 열기</label></p>');
$('#open-motorcad-after').checked=state.openMotorcadAfter===true;
document.addEventListener('change',e=>{
  const t=e.target;
  if(t.id==='op-current-control'||t.id==='op-field-weakening'){
    e.stopImmediatePropagation();const o=state.ops[state.activeOp];
    if(t.id==='op-current-control')o.currentControl=t.value;else o.fieldWeakening=t.checked;
    persist();return;
  }
  if(t.id==='open-motorcad-after'){e.stopImmediatePropagation();state.openMotorcadAfter=t.checked;persist();}
  if(t.id.startsWith('motorcad-condition-'))e.stopImmediatePropagation();
},true);
document.addEventListener('click',async e=>{
  if(e.target.closest('#engine-example')){$('#open-motorcad-after').checked=false;state.openMotorcadAfter=false;persist();render();}
  const b=e.target.closest('[data-open-motorcad]');if(!b)return;
  const feedback=$('#motorcad-open-feedback');b.disabled=true;
  try{
    const label=$('#motorcad-condition-'+b.dataset.conditionIndex).value;
    const response=await fetch('/api/motorcad/open',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:realJob.id,model_id:b.dataset.openMotorcad,label})});
    const data=await response.json();if(!response.ok)throw Error(data.error);
    feedback.textContent='Motor-CAD를 여는 중입니다…';
  }catch(err){feedback.textContent='열기 실패: '+err.message;}finally{b.disabled=false;}
});
const pollBeforeViewer=pollJob;
pollJob=async function(){
  await pollBeforeViewer();const s=realJob?.motorcad_open,feedback=$('#motorcad-open-feedback');
  if(s&&feedback)feedback.textContent=s.status==='opened'?`${s.model_id} / ${s.label} 설정을 Motor-CAD에서 열었습니다.`:s.status==='failed'?'열기 실패: '+s.error:'Motor-CAD를 여는 중입니다…';
};
// The original polling interval captured the previous function; keep viewer
// feedback fresh without starting a second network polling loop.
setInterval(()=>{const s=realJob?.motorcad_open,f=$('#motorcad-open-feedback');if(s&&f)f.textContent=s.status==='opened'?`${s.model_id} / ${s.label} 설정을 Motor-CAD에서 열었습니다.`:s.status==='failed'?'열기 실패: '+s.error:'Motor-CAD를 여는 중입니다…';},1500);
const renderBeforeCurrentPolicy=render;
render=function(){renderBeforeCurrentPolicy();$('#open-motorcad-after').checked=state.openMotorcadAfter===true;};
render();
