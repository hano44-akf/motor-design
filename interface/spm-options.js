/* A shared catalog drives selection; registration never implies qualification. */
let rotorCatalog=null,rotorCatalogError='';
let spmShapes=['Radial','Breadloaf','Parallel'];
const spmDirections=['Radial','Parallel'];
function rotorSpec(shape=state.spm?.shape){
  return rotorCatalog?.rotors.find(r=>r.id===shape||r.input_value===shape||r.aliases.includes(shape));
}
function ensureSpmOptions(){
  state.spm=state.spm||{};
  if(!state.spm.shape)state.spm.shape='Radial';
  const spec=rotorSpec();
  if(!state.spm.magnetisation)state.spm.magnetisation=spec?.direction_policy==='template_pending'?'Template':'Radial';
}
function rotorLabel(shape){return rotorSpec(shape)?.label||('Surface '+shape);}
function spmPanel(){
  ensureSpmOptions();const spec=rotorSpec(),caps=spec?.capabilities;
  const groups=rotorCatalog?['Surface','Inset','Embedded','Interior','Spoke'].map(g=>`<optgroup label="${g}">${rotorCatalog.rotors.filter(r=>r.family===g).map(r=>`<option value="${esc(r.input_value)}" ${state.spm.shape===r.input_value||state.spm.shape===r.id?'selected':''}>${esc(r.label)}</option>`).join('')}</optgroup>`).join(''):spmShapes.map(s=>`<option ${state.spm.shape===s?'selected':''}>${s}</option>`).join('');
  const direction=spec?.direction_policy==='template_pending'?'<option value="Template">템플릿 착자 · SDK 매핑 준비중</option>':spmDirections.map(v=>`<option ${state.spm.magnetisation===v?'selected':''}>${v}</option>`).join('');
  const status=caps?`<p>입력 매핑: <b>${caps.input_mapping_verified?'확인됨':'준비중'}</b> / 형상 계산: <b>${caps.geometry_adapter_available?'기존 템플릿':'준비중'}</b> / 현재 착자 수식 예측: <b>${caps.formula_reference_directions.includes(state.spm.magnetisation)?'연결됨 · 근사':'준비중'}</b></p>`:'<p class="muted">회전자 카탈로그를 불러오는 중입니다.</p>';
  return panel('BPM 회전자 형상 · 착자 방향',
    `<label class="field"><span>회전자 타입 · 기본 16종</span><select data-spm="shape">${groups}</select><span></span></label>`+
    `<label class="field"><span>착자 방향</span><select data-spm="magnetisation" ${spec?.direction_policy==='template_pending'?'disabled':''}>${direction}</select><span></span></label>`+
    status+'<p class="muted">형상의 Parallel과 착자 방향은 별도 설정입니다. 타입 등록·입력 매핑·성능 예측·실제 검증 완료를 구분합니다. 스큐는 기능에서 제외했습니다.</p>'+
    (rotorCatalogError?`<p class="error">${esc(rotorCatalogError)}</p>`:'')+
    '<div class="notice">현재 실행 모델은 Surface Radial/Radial 및 Surface Parallel/Parallel의 4극·12슬롯입니다. 나머지는 상세 변수 입력·저장과 준비 상태 확인이 가능하며, 미연결 타입을 기존 Radial 모델로 계산하지 않습니다.</div>');
}
const basicBeforeSpm=basic;
basic=function(){return spmPanel()+basicBeforeSpm();};
const geometryBeforeSpm=geometry;
geometry=function(){return spmPanel()+geometryBeforeSpm();};
const renderBeforeSpm=render;
render=function(){ensureSpmOptions();renderBeforeSpm();};
document.addEventListener('change',e=>{
  const t=e.target;if(!t.dataset.spm)return;e.stopImmediatePropagation();
  state.rotorDirections=state.rotorDirections||{};
  if(t.dataset.spm==='shape'){
    const before=rotorSpec();if(before)state.rotorDirections[before.id]=state.spm.magnetisation;
    state.spm.shape=t.value;const after=rotorSpec();
    state.spm.magnetisation=after?.direction_policy==='template_pending'?'Template':state.rotorDirections[after?.id]||'Radial';
  }else state.spm.magnetisation=t.value;
  persist();render();
},true);
fetch('/api/rotor-catalog').then(r=>{if(!r.ok)throw Error('카탈로그 서버 연결 실패');return r.json();}).then(data=>{
  rotorCatalog=data;spmShapes=data.rotors.map(r=>r.input_value);ensureSpmOptions();render();
}).catch(e=>{rotorCatalogError=e.message;render();});
render();
