/* Draft per-type variables, pole/slot candidates and user manufacturing limits. */
const standardPoleSlots=[[4,12],[8,12],[10,12],[14,12],[8,9],[10,9],[8,18],[10,18],[16,18],[10,24],[14,24]].map(([poles,slots])=>({poles,slots}));
function ensureRotorDraft(){
  state.rotorParameters=state.rotorParameters||{};state.rotorEditingLayer=state.rotorEditingLayer||{};
  state.statorParameters=state.statorParameters||{};
  if(!Array.isArray(state.poleSlotCandidates))state.poleSlotCandidates=[{poles:Number(state.geometry.poles)||4,slots:Number(state.geometry.slots)||12}];
  state.extraPoleSlotPairs=state.extraPoleSlotPairs||[];
  const spec=rotorSpec();if(spec){
    if(state.spm.parameters&&!state.rotorParameters[spec.id])state.rotorParameters[spec.id]=structuredClone(state.spm.parameters);
    delete state.spm.parameters;state.rotorParameters[spec.id]=state.rotorParameters[spec.id]||{};
  }
}
function draftOptions(){
  ensureRotorDraft();const spec=rotorSpec();const options={...state.spm};
  const parameters=spec?state.rotorParameters[spec.id]:{};
  if(Object.keys(parameters||{}).length)options.parameters=structuredClone(parameters);else delete options.parameters;
  return options;
}
function polePairKey(pair){return pair.poles+'/'+pair.slots;}
function poleSlotPanel(){
  ensureRotorDraft();const pairs=[...new Map([...standardPoleSlots,...state.extraPoleSlotPairs,...state.poleSlotCandidates].map(v=>[polePairKey(v),v])).values()];
  return panel('극·슬롯 조합 후보 · 스큐 제외',
    `<div class="checks">${pairs.map(v=>`<label><input type="checkbox" data-pole-slot="${v.poles}/${v.slots}" ${state.poleSlotCandidates.some(x=>polePairKey(x)===polePairKey(v))?'checked':''}>${v.poles}극 / ${v.slots}슬롯 ${v.poles===4&&v.slots===12?'· 기존 모델':'· 권선/모델 준비중'}</label>`).join('')}</div>`+
    '<div class="field"><span>사용자 조합 · 극수 / 슬롯수</span><span style="display:flex;gap:5px"><input id="new-poles" type="number" min="2" step="2" aria-label="추가할 극수"><input id="new-slots" type="number" min="3" step="1" aria-label="추가할 슬롯수"></span><button id="add-pole-slot">추가</button></div><p id="pole-slot-error" class="error"></p>'+
    `<p>선택 조합 ${state.poleSlotCandidates.length}개. 4극·12슬롯 외에는 권선 배치·권선계수·성능 모델 연결이 필요합니다. 표시는 권선 성립이나 리플 성능을 보증하지 않습니다.</p>`);
}
function rotorParameterPanel(){
  ensureRotorDraft();const spec=rotorSpec();if(!spec)return '';
  const defs=rotorCatalog.parameter_definitions,values=state.rotorParameters[spec.id],layer=state.rotorEditingLayer[spec.id]||1;
  const rows=spec.parameters.map(base=>{
    const def=defs[base],key=spec.layered&&spec.layer_parameters.includes(base)?`L${layer}.${base}`:base;
    const setting=values[key]||{mode:'auto'},m=setting.mode;
    return `<tr><td>${esc(key.startsWith('L')?'L'+layer+' ':'')}${esc(def.label)}${def.structural_section?' · 최소두께 적용':''}</td><td><select data-rotor-mode="${esc(key)}">${[['auto','미지정'],['fixed','고정'],['range','범위']].map(([value,label])=>`<option value="${value}" ${m===value?'selected':''}>${label}</option>`).join('')}</select></td><td><input type="number" step="${def.step||'any'}" data-rotor-param="${esc(key)}" data-bound="${m==='range'?'min':'value'}" value="${esc(m==='range'?setting.min:setting.value)}" ${m==='auto'?'disabled':''} aria-label="${esc(key)} 하한 또는 고정값"></td><td><input type="number" step="${def.step||'any'}" data-rotor-param="${esc(key)}" data-bound="max" value="${esc(setting.max)}" ${m!=='range'?'disabled':''} aria-label="${esc(key)} 상한"></td><td>${esc(def.unit)}</td></tr>`;
  }).join('');
  return panel(`${esc(spec.label)} 상세 변수 · 등록 단계`,
    (spec.layered?`<label class="field"><span>편집할 층 번호 · 실제 층 수는 Magnet Layers</span><input id="rotor-editing-layer" type="number" step="1" min="1" value="${layer}"><span></span></label>`:'')+
    `<div class="scroll"><table><tr><th>항목</th><th>방식</th><th>고정/하한</th><th>상한</th><th>단위</th></tr>${rows}</table></div>`+
    '<p class="muted">형상별 초안 스키마입니다. 길이는 mm·0.1 mm 격자, 각도는 표기된 기계각/전기각 기준입니다. 소재 두께는 별도 물성값이므로 0.1 mm로 반올림하지 않습니다. 기존 5변수 엔진은 상세 설정을 무시하지 않고 차단합니다.</p>'+
    (spec.id==='surface_breadloaf'?'<p class="muted">별도 Breadloaf 리플 작업에서는 극호 40~100 ED(0.1 ED 격자)와 reduction 0~1.5 mm의 고정/범위를 반영합니다. 슬롯 입구 1~3 mm는 아래 상세 형상 표에서 설정합니다. 다른 치수의 탐색 연결은 아직 미지원입니다.</p>':'<p class="muted">현재 이 형상의 상세 변수는 저장·기본 검사 단계입니다.</p>'));
}
function rotorManufacturingPanel(){
  return panel('회전자 제조 최소 두께',
    '<p>브리지·리브·웹 및 존재하는 구조 포스트의 최소값은 <b>max(0.5 mm, 실제 소재 두께)</b>입니다. 소재 미확인 시 임의로 제조 가능 판정을 하지 않습니다.</p>'+
    `<label class="field"><span>실제 소재 두께 · 공란이면 재질 DB</span><input type="number" step="any" id="rotor-sheet-thickness" value="${esc(state.rotorLaminationThicknessMm)}" placeholder="재질 DB 사용"><span>mm</span></label>`+
    '<p class="muted">50PN470의 소재 두께는 0.5 mm입니다. 제조 최소 치수는 유지하며 열·구조 해석은 제외합니다. 감자·리플은 전자기 검증 항목입니다.</p><div id="rotor-preflight" aria-live="polite">설정 준비 상태 확인 중…</div>');
}
function detailedStatorPanel(){
  const spec=rotorSpec(),schema=rotorCatalog?.detailed_spm_geometry;
  if(!schema?.registered_rotor_ids.includes(spec?.id))return '';
  const rows=Object.entries(schema.stator_parameters).map(([key,def])=>{
    const s=state.statorParameters[key]||{mode:'auto'};
    return `<tr><td>${esc(def.label)}</td><td><select data-stator-mode="${key}">${[['auto','비례 초기값'],['fixed','고정'],['range','범위']].map(([v,l])=>`<option value="${v}" ${s.mode===v?'selected':''}>${l}</option>`).join('')}</select></td><td><input type="number" step="0.1" data-stator-param="${key}" data-bound="${s.mode==='range'?'min':'value'}" value="${esc(s.mode==='range'?s.min:s.value)}" ${s.mode==='auto'?'disabled':''} aria-label="${esc(def.label)} 고정 또는 하한"></td><td><input type="number" step="0.1" data-stator-param="${key}" data-bound="max" value="${esc(s.max)}" ${s.mode==='range'?'':'disabled'} aria-label="${esc(def.label)} 상한"></td><td>mm</td></tr>`;
  }).join('');
  return panel('SPM 상세 형상 · 형상 검사',`<div class="scroll"><table><tr><th>치수</th><th>방식</th><th>고정/하한</th><th>상한</th><th>단위</th></tr>${rows}</table></div><p class="muted">이 표는 항상 mm 기준이며 독립 길이 입력은 0.1 mm 단위입니다. 자동 항목은 비례 초기값, 범위 항목은 중간점을 사용해 형상을 검사합니다. 범위 전체의 성립이나 성능 최적화 완료를 뜻하지 않습니다.</p><button id="spm-geometry-preview">상세 형상 검사·저장 · 해석 없음</button><div id="spm-geometry-result" aria-live="polite"></div>`);
}
function spmGeometryRequest(){
  const factor=unitChoices.length.options[state.units];
  const seed=(key,fallback)=>{
    const m=mode(key),r=state.ranges[key]||{};
    const v=m==='fixed'?Number(state.geometry[key])*factor:m==='range'?(Number(r.min)+Number(r.max))/2*factor:fallback;
    return Math.round(v*10)/10;
  };
  const data={spm:draftOptions(),core:state.core.length===1?'POSCO | '+state.core[0]:'',
    geometry_parameters:structuredClone(state.statorParameters),pole_slot_candidates:structuredClone(state.poleSlotCandidates),
    dimensions:{diameter_mm:seed('od',85),length_mm:seed('length',20)},airgap_bounds_mm:gapBounds(),manufacturing:{}};
  if(state.rotorLaminationThicknessMm!==''&&state.rotorLaminationThicknessMm!==undefined)data.manufacturing.lamination_thickness_mm=Number(state.rotorLaminationThicknessMm);
  return data;
}
const geometryBeforeRotorDraft=geometry;
geometry=function(){
  const html=geometryBeforeRotorDraft().replace(/(<select[^>]*data-mode="(?:poles|slots)"[^>]*)(>)/g,'$1 disabled title="극·슬롯 조합 후보에서 설정"$2');
  return html+poleSlotPanel()+rotorParameterPanel()+detailedStatorPanel()+rotorManufacturingPanel();
};
const studyBeforeRotorDraft=toStudyRequest;
toStudyRequest=function(){
  ensureRotorDraft();const request=studyBeforeRotorDraft();
  if(!state.poleSlotCandidates.length)throw Error('극·슬롯 조합을 하나 이상 선택하세요.');
  request.spm=draftOptions();request.pole_slot_candidates=structuredClone(state.poleSlotCandidates);
  if(Object.keys(state.statorParameters).length)request.geometry_parameters=structuredClone(state.statorParameters);
  request.manufacturing={};const sheet=state.rotorLaminationThicknessMm;
  if(sheet!==''&&sheet!==undefined&&sheet!==null){if(!Number.isFinite(Number(sheet))||Number(sheet)<=0)throw Error('소재 두께는 양수여야 합니다.');request.manufacturing.lamination_thickness_mm=Number(sheet);}
  return request;
};
let rotorPreflightTimer;
function rotorReasonText(message){
  const exact={
    'Matching rotor/direction reference and performance model are not connected':'이 형상·착자 조합의 기준 자료와 성능 계산 모델을 준비 중입니다.',
    'Rotor-specific geometry adapter is not connected':'이 회전자의 전용 형상 생성·검사 기능을 준비 중입니다.',
    'Actual lamination thickness differs from the material record; matching loss/performance model required':'실제 소재 두께가 재질 DB와 다릅니다. 해당 두께의 손실·성능 모델을 확인해야 합니다.'
  };
  if(exact[message])return exact[message];
  if(message.startsWith('Detailed parameters are registered'))return '상세 변수 최적화 연결 전입니다: '+message.split(': ').slice(1).join(': ');
  const pair=message.match(/^(\d+) poles \/ (\d+) slots:/);if(pair)return `${pair[1]}극 / ${pair[2]}슬롯의 권선·성능 모델을 준비 중입니다.`;
  const minimum=message.match(/^(.+) must be >= ([0-9.]+) mm/);if(minimum)return `${minimum[1]}는 ${minimum[2]} mm 이상이어야 합니다. 최소값은 0.5 mm와 실제 소재 두께 중 큰 값입니다.`;
  if(message.startsWith('Matching reference condition not connected:'))return '선택 조건에 맞는 기준 자료가 필요합니다: '+message.split(': ')[1];
  return message;
}
async function refreshRotorPreflight(){
  const node=$('#rotor-preflight');if(!node)return;
  try{
    const spec=rotorSpec(),sheet=state.rotorLaminationThicknessMm;
    const data={spm:draftOptions(),core:state.core.length===1?'POSCO | '+state.core[0]:'',
      pole_slot_candidates:state.poleSlotCandidates,geometry_parameters:state.statorParameters,manufacturing:{},operating_point:{}};
    if(state.ops[0]?.rpm>0)data.operating_point.speed_rpm=state.ops[0].rpm;
    if(state.switchingKHz!==''&&state.switchingKHz!==undefined)data.switching_frequency_hz=Number(state.switchingKHz)*1000;
    if(sheet!==''&&sheet!==undefined&&sheet!==null)data.manufacturing.lamination_thickness_mm=Number(sheet);
    const response=await fetch('/api/rotor/preflight',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    const result=await response.json();if(!response.ok)throw Error(result.error);
    if($('#rotor-preflight')!==node||rotorSpec()?.id!==spec.id)return;
    const rule=result.manufacturing;
    const windingHtml='<h4>극·슬롯별 권선 계산</h4><div class="scroll"><table id="pole-slot-winding-review"><tr><th>극 / 슬롯</th><th>코일 스팬 / 층수</th><th>기본파 권선계수</th><th>3상 균형</th><th>전기 주파수</th><th>PWM 제한</th></tr>'+
      result.pole_slot_review.map(pair=>{const w=pair.winding_analysis;if(!w)return '';return `<tr><td>${pair.poles} / ${pair.slots}</td><td>${w.coil_span_slots} 슬롯 / ${w.layers}층</td><td>${w.fundamental_winding_factors.map(v=>v.toFixed(4)).join(' / ')}</td><td>${w.balanced?'수식 확인':'지원 권선군에서 불성립'}</td><td>${pair.electrical_frequency_Hz==null?'RPM 미입력':pair.electrical_frequency_Hz.toFixed(2)+' Hz'}</td><td>${pair.pwm_check==null?'미확인':pair.pwm_check.passes?'통과':'제외'}</td></tr>`;}).join('')+'</table></div><p class="muted">동일 턴수 3상 2층 권선 후보입니다. 4극·12슬롯은 기존 스팬 2를 유지합니다. 권선계수만으로 효율·토크 리플을 판정하지 않으며, 새 조합은 Motor-CAD 권선표 대조와 전용 성능 모델이 필요합니다.</p>'+
      '<details><summary>슬롯별 권선표 및 고조파 권선계수</summary><pre style="max-height:300px;overflow:auto">'+esc(JSON.stringify(result.pole_slot_review.map(p=>({poles:p.poles,slots:p.slots,winding:p.winding_analysis})),null,2))+'</pre></details>';
    node.innerHTML=`<p>적용 최소 두께: <b>${rule.effective_minimum_mm===null?'소재 두께 미확정':rule.effective_minimum_mm+' mm'}</b>${rule.grid_minimum_mm!==null?' / 0.1 mm 격자 최소 '+rule.grid_minimum_mm+' mm':''}</p><p>${result.executable?'현재 5변수 계산 경로 사용 가능 · 설계 검증 완료는 아님':'설정 저장 가능 · 계산 경로 준비중'}</p>`+
      (result.blocking_reasons.length?'<ul>'+result.blocking_reasons.map(v=>`<li>${esc(rotorReasonText(v))}</li>`).join('')+'</ul>':'')+
      `<p class="muted">극·슬롯 조합 ${result.pole_slot_review.length}개 / 스큐 제외 / 전체 설계 검증 미완료</p>`;
    node.insertAdjacentHTML('beforeend',windingHtml);
    node.insertAdjacentHTML('beforeend','<button id="save-topology-plan" type="button">일괄 검증 대기 목록 저장 · 해석 없음</button><p id="topology-plan-status" aria-live="polite"></p>');
  }catch(e){if($('#rotor-preflight')===node)node.innerHTML=`<p class="error">${esc(rotorReasonText(e.message))}</p>`;}
}
function queueRotorPreflight(){clearTimeout(rotorPreflightTimer);rotorPreflightTimer=setTimeout(refreshRotorPreflight,160);}
function syncPairGeometry(){
  if(state.poleSlotCandidates.length===1){const pair=state.poleSlotCandidates[0];state.geometry.poles=pair.poles;state.geometry.slots=pair.slots;state.modes.poles='fixed';state.modes.slots='fixed';}
  else{for(const key of ['poles','slots']){delete state.geometry[key];state.modes[key]='auto';}}
}
document.addEventListener('change',e=>{
  const t=e.target;
  if(t.dataset.statorMode){e.stopImmediatePropagation();ensureRotorDraft();if(t.value==='auto')delete state.statorParameters[t.dataset.statorMode];else state.statorParameters[t.dataset.statorMode]={mode:t.value};persist();render();}
  if(t.dataset.rotorMode){e.stopImmediatePropagation();ensureRotorDraft();const v=state.rotorParameters[rotorSpec().id];
    if(t.value==='auto')delete v[t.dataset.rotorMode];else v[t.dataset.rotorMode]={mode:t.value};persist();render();}
  if(t.dataset.poleSlot){e.stopImmediatePropagation();const [poles,slots]=t.dataset.poleSlot.split('/').map(Number);
    state.poleSlotCandidates=t.checked?[...state.poleSlotCandidates,{poles,slots}]:state.poleSlotCandidates.filter(x=>polePairKey(x)!==t.dataset.poleSlot);
    syncPairGeometry();persist();render();}
  if(t.id==='rotor-editing-layer'){e.stopImmediatePropagation();if(Number.isSafeInteger(Number(t.value))&&Number(t.value)>0){state.rotorEditingLayer[rotorSpec().id]=Number(t.value);persist();render();}}
},true);
document.addEventListener('input',e=>{
  const t=e.target;
  if(t.dataset.statorParam){e.stopImmediatePropagation();ensureRotorDraft();const key=t.dataset.statorParam;state.statorParameters[key]=state.statorParameters[key]||{mode:'fixed'};
    if(t.value==='')delete state.statorParameters[key][t.dataset.bound];else state.statorParameters[key][t.dataset.bound]=Number(t.value);persist();queueRotorPreflight();}
  if(t.dataset.rotorParam){e.stopImmediatePropagation();ensureRotorDraft();const p=state.rotorParameters[rotorSpec().id];p[t.dataset.rotorParam]=p[t.dataset.rotorParam]||{mode:'fixed'};
    if(t.value==='')delete p[t.dataset.rotorParam][t.dataset.bound];else p[t.dataset.rotorParam][t.dataset.bound]=Number(t.value);persist();queueRotorPreflight();}
  if(t.id==='rotor-sheet-thickness'){e.stopImmediatePropagation();state.rotorLaminationThicknessMm=t.value===''?'':Number(t.value);persist();queueRotorPreflight();}
},true);
document.addEventListener('click',e=>{
  if(e.target.closest('#spm-geometry-preview')){
    const button=e.target.closest('#spm-geometry-preview'),target=$('#spm-geometry-result');button.disabled=true;target.textContent='형상 검사 중…';
    (async()=>{try{
      const response=await fetch('/api/geometry/spm/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(spmGeometryRequest())});
      const data=await response.json();if(!response.ok)throw Error(data.error);
      target.innerHTML=`<p>대표 초기값: 외경 ${data.seed_dimensions_mm.diameter_mm} mm / 적층 ${data.seed_dimensions_mm.length_mm} mm · 해석 0회</p><div class="scroll"><table><tr><th>극/슬롯</th><th>요크 두께 mm</th><th>자석 두께 mm</th><th>극호 ED</th><th>Reduction mm</th><th>외곽 검사</th></tr>${data.designs.map(d=>`<tr><td>${d.pair.poles}/${d.pair.slots}</td><td>${d.derived_geometry.stator_yoke_thickness_mm.toFixed(3)}</td><td>${d.native_dimension_candidates.Magnet_Thickness}</td><td>${d.magnet_arc_ed}</td><td>${d.breadloaf_reduction_mm??'해당 없음'}</td><td>${d.envelope_checks_passed?'기본 조건 통과':esc(d.violations.join(', '))}</td></tr>`).join('')}</table></div><p class="muted">파생 치수는 반올림하지 않고 표시합니다. Breadloaf 코너 두께·완전한 기하 성립·B·리플은 미검증이며 기존 5변수 성능 최적화에는 아직 연결되지 않았습니다.</p><details><summary>형상 변수·입력 상세</summary><pre style="max-height:320px;overflow:auto">${esc(JSON.stringify(data.designs,null,2))}</pre></details><p class="muted">저장 위치: ${esc(data.saved_folder)}</p>`;
    }catch(error){target.textContent=error.message;}finally{button.disabled=false;}})();
  }
  if(e.target.closest('#save-topology-plan')){
    const button=e.target.closest('#save-topology-plan'),status=$('#topology-plan-status');
    button.disabled=true;status.textContent='저장 중…';
    (async()=>{try{
      const response=await fetch('/api/topology/plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(toStudyRequest())});
      const result=await response.json();if(!response.ok)throw Error(result.error);
      status.textContent=`검증 대기 ${result.pending_task_count}개 저장 · 해석 0회: ${result.folder}`;
    }catch(error){status.textContent=error.message;}finally{button.disabled=false;}})();
  }
  if(e.target.closest('#add-pole-slot')){
    const poles=Number($('#new-poles').value),slots=Number($('#new-slots').value);
    if(!Number.isSafeInteger(poles)||poles<2||poles%2||!Number.isSafeInteger(slots)||slots<3){$('#pole-slot-error').textContent='극수는 2 이상 짝수, 슬롯수는 3 이상 정수로 입력하세요.';return;}
    const pair={poles,slots};if(!state.extraPoleSlotPairs.some(v=>polePairKey(v)===polePairKey(pair)))state.extraPoleSlotPairs.push(pair);
    if(!state.poleSlotCandidates.some(v=>polePairKey(v)===polePairKey(pair)))state.poleSlotCandidates.push(pair);syncPairGeometry();persist();render();
  }
  if(e.target.closest('#engine-example')){state.poleSlotCandidates=[{poles:4,slots:12}];state.rotorParameters={};state.statorParameters={};state.rotorLaminationThicknessMm='';persist();render();}
});
const renderBeforeRotorDraft=render;
render=function(){ensureRotorDraft();renderBeforeRotorDraft();queueRotorPreflight();};
render();
