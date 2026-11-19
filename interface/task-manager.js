/* Independent task UI. It owns its state and never replaces legacy render/input functions. */
const labels={planned:'대기',ready:'준비됨',running:'실행 중',completed:'완료',failed:'실패',blocked:'보류',stopped:'중단됨',interrupted:'중단 확인 필요'};
const kinds={mock:'모의 작업',formula:'수식 최적화',motorcad_verify:'Motor-CAD 후보 검증',motorcad_diagnostic:'Motor-CAD 진단',motorcad_mesh:'Motor-CAD 메시 비교',manual_check:'검증 준비 항목'};
const nativeKinds=new Set(['motorcad_verify','motorcad_diagnostic','motorcad_mesh']);
const reasons={execution_recipe_required:'구체적인 모델·해석 조건 등록 필요',dependency_not_completed:'선행 작업이 아직 완료되지 않음',native_execution_not_enabled:'Motor-CAD 실행 선택 필요',prior_native_failure_review_required:'앞선 해석의 오류·남은 프로세스 확인 필요',interrupted_worker_review_required:'중단된 워커의 부분 결과 확인 필요',completed_artifact_changed:'완료 결과 파일이 변경되거나 없음',input_changed:'입력 파일 변경됨 · 새 계획 등록 필요',execution_failed:'실행 실패 · 로그 확인 필요'};
const model={jobs:[],selected:null,detail:null,retries:new Set(),native:false,reviewed:false,busy:false,notice:'',error:'',auto:false,tab:'tasks',result:null};
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=value=>Number.isFinite(value)?new Date(value*1000).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false}):'—';
const duration=value=>Number.isFinite(value)?value<60?`${value.toFixed(1)}초`:`${(value/60).toFixed(1)}분`:'미정';
const badge=value=>`<span class="tm-badge tm-${escape(value)}">${escape(labels[value]||value)}</span>`;
const planTitle=title=>title==='Imported verification preparation checklist'?'기존 검증 준비 목록':title;
function taskTitle(task){
  if(task.payload?.title)return task.payload.title;
  if(task.kind==='motorcad_verify')return '후보 '+(task.payload.request?.selected_model_ids||[]).join(', ')+' 검증';
  if(task.kind==='mock'&&typeof task.payload?.value==='string')return task.payload.value;
  return kinds[task.kind]||task.id;
}
let timer=null,loadToken=0;
const modal=document.createElement('dialog');modal.id='task-manager-modal';modal.className='tm-dialog';
modal.innerHTML=`<div class="tm-header"><div><h2>작업 관리</h2><p>백그라운드 실행 · 진행 기록 · 중단 및 재개</p></div><button id="tm-close" aria-label="작업 관리 닫기">닫기</button></div>
<div class="tm-toolbar"><button id="tm-refresh">새로고침</button><label><input type="checkbox" id="tm-auto"> 5초마다 상태 갱신</label><span class="tm-spacer"></span><button id="tm-import">기존 검증 목록 가져오기</button></div>
<div class="tm-create"><button id="tm-create-formula">현재 입력 수식작업 등록</button><button id="tm-create-verification">선택 후보 검증계획 등록</button><details><summary>모의 실행 점검</summary><button id="tm-create-mock">모의 실패·재개 예제 등록</button><span class="muted">Motor-CAD를 실행하지 않습니다.</span></details></div>
<div id="tm-notice" role="status" aria-live="polite"></div><div id="tm-error" role="alert"></div>
<div class="tm-layout"><section class="tm-jobs"><h3>작업 계획</h3><div id="tm-job-list"></div></section><section id="tm-detail" class="tm-detail" aria-label="선택한 작업 계획"></section></div>
<p class="tm-footnote">창을 닫아도 백그라운드 작업은 계속됩니다. 작업 완료와 모터 요구조건 합격은 별도입니다.</p>`;
document.body.append(modal);
const openButton=document.createElement('button');openButton.id='task-manager-open';openButton.textContent='작업 관리';document.querySelector('.toolbar').append(openButton);
const node=id=>modal.querySelector('#'+id);

async function api(path,data){
  const response=await fetch(path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const body=await response.json();if(!response.ok)throw Error(body.error||`요청 실패 (${response.status})`);return body;
}
function errorText(error){
  const message=error.message||String(error);
  if(message.includes('Implementation changed'))return '프로그램이 변경돼 이 계획을 실행할 수 없습니다. 현재 입력으로 새 계획을 등록하세요.';
  if(message.includes('worker is already active'))return '다른 작업이 실행 중입니다. 종료 후 다시 시작하세요.';
  if(message.includes('Review partial'))return '부분 결과와 남은 프로세스를 확인한 뒤 확인 항목을 선택하세요.';
  return message;
}
function renderNotices(){node('tm-notice').textContent=model.notice;node('tm-error').textContent=model.error;modal.setAttribute('aria-busy',String(model.busy));}
function resultURL(task,attempt,file){return '/api/task-queue/artifact?'+new URLSearchParams({job:model.selected,task,attempt:String(attempt),file});}
function selectedFailed(){return model.detail?.tasks.filter(t=>t.state==='failed'&&model.retries.has(t.id))||[];}
function needsReview(task){return nativeKinds.has(task.kind)||['interrupted_worker_review_required','completed_artifact_changed'].includes(task.reason);}
function eligibility(){
  const d=model.detail;if(!d)return {};
  const busy=model.busy||d.worker_active;
  const compatible=d.implementation_compatible!==false;
  const unfinished=d.tasks.some(t=>['planned','ready','blocked','running'].includes(t.state)&&t.kind!=='manual_check'&&(!nativeKinds.has(t.kind)||model.native)&&
    (t.state==='running'||(t.deps||[]).every(id=>d.tasks.some(parent=>parent.id===id&&parent.state==='completed'))));
  const selected=selectedFailed();
  return {start:!busy&&compatible&&unfinished,resume:!busy&&compatible&&unfinished,
    retry:!busy&&compatible&&selected.length>0&&!selected.some(t=>t.reason==='input_changed')&&(!selected.some(needsReview)||model.reviewed)&&(!selected.some(t=>nativeKinds.has(t.kind))||model.native)};
}
function renderList(){
  node('tm-job-list').innerHTML=model.jobs.length?model.jobs.map(j=>`<button class="tm-job ${model.selected===j.id?'tm-selected':''}" data-tm-job="${escape(j.id)}"><strong>${escape(planTitle(j.title))}</strong><span>${badge(j.state)} <small>${escape(time(j.updated))}</small></span></button>`).join(''):'<p class="tm-empty">등록된 작업이 없습니다.<br>현재 입력 또는 검증 목록을 등록하세요.</p>';
}
function renderDetail(){
  const d=model.detail;
  if(!d){node('tm-detail').innerHTML='<div class="tm-empty">왼쪽에서 작업 계획을 선택하세요.</div>';return;}
  const progress=d.total_tasks?d.completed_tasks/d.total_tasks*100:0;
  const nativeTasks=d.tasks.filter(t=>nativeKinds.has(t.kind));
  const e=eligibility();
  node('tm-detail').innerHTML=`<div class="tm-detail-title"><div><h3>${escape(planTitle(d.title))}</h3><small>${escape(d.id)} · ${escape(time(d.created))}</small></div>${badge(d.state)}</div>
  <div class="tm-metrics"><div><small>완료 / 전체</small><strong>${d.completed_tasks} / ${d.total_tasks}</strong></div><div><small>실행 중 / 보류 / 실패</small><strong>${d.counts.running||0} / ${d.counts.blocked||0} / ${d.counts.failed||0}</strong></div><div><small>등록 기준 남은 예상 시간</small><strong>${duration(d.estimated_remaining_s)}</strong></div></div>
  <progress id="tm-progress" max="100" value="${progress}" aria-label="전체 작업 완료율"></progress><p class="muted">${d.unestimated_tasks?`예상 시간이 없는 항목 ${d.unestimated_tasks}개 · 전체 완료 시각은 미정입니다.`:'실행 중 작업의 경과시간을 차감하지 않은 등록 기준 추정입니다.'}</p>
  ${d.implementation_compatible===false?'<p class="tm-warning">프로그램 버전이 변경됐습니다. 기록은 조회할 수 있으며, 실행하려면 새 계획을 등록해야 합니다.</p>':''}
  <div class="tm-execution-options">${nativeTasks.length?`<label><input type="checkbox" id="tm-native" ${model.native?'checked':''}> 이 계획의 Motor-CAD 작업 ${nativeTasks.length}개 실행 포함</label><p class="muted">선택한 실행 항목은 아래 표와 입력 상세에서 확인하세요. 작업 개수와 개별 해석 횟수는 다를 수 있습니다.</p>`:'<p class="muted">이 계획은 Motor-CAD 실행 작업을 포함하지 않습니다.</p>'}
  ${selectedFailed().some(needsReview)?`<label><input type="checkbox" id="tm-reviewed" ${model.reviewed?'checked':''}> 선택한 실패 작업의 부분 결과와 남은 프로세스를 확인했습니다.</label>`:''}</div>
  <div class="tm-actions"><button id="tm-start" class="primary" ${e.start?'':'disabled'}>시작</button><button id="tm-stop" ${!model.busy&&d.worker_active&&d.state==='running'?'':'disabled'}>중단 요청</button><button id="tm-resume" ${e.resume?'':'disabled'}>남은 작업 재개</button><button id="tm-retry" ${e.retry?'':'disabled'}>선택한 실패 작업 재시도 (${selectedFailed().length})</button></div>
  <div class="tm-tabs" role="tablist" aria-label="작업 정보">${[['tasks','작업 목록'],['attempts','실행 이력'],['result','결과 보기']].map(([id,label])=>`<button role="tab" aria-selected="${model.tab===id}" data-tm-tab="${id}">${label}</button>`).join('')}</div>
  <div id="tm-tab-content"></div>`;
  renderTab();
}
function renderTab(){
  const d=model.detail;if(!d)return;
  const area=node('tm-tab-content');
  if(model.tab==='tasks'){
    area.innerHTML=`<div class="tm-scroll"><table><thead><tr><th>재시도</th><th>작업 / 종류</th><th>상태 / 보류 사유</th><th>선행 작업</th><th>시도</th><th>예상</th><th>결과</th></tr></thead><tbody>${d.tasks.map(t=>`<tr><td>${t.state==='failed'?`<input type="checkbox" data-tm-retry="${escape(t.id)}" aria-label="${escape(t.id)} 재시도 선택" ${model.retries.has(t.id)?'checked':''}>`:'—'}</td><td><strong>${escape(taskTitle(t))}</strong><small class="tm-block">${escape(kinds[t.kind]||t.kind)} ? ${escape(t.id)}</small><details><summary>입력 상세</summary><pre>${escape(JSON.stringify(t.payload,null,2))}</pre></details></td><td>${badge(t.state)}<small class="tm-block">${escape(reasons[t.reason]||t.reason||'')}</small>${t.error?`<details><summary>오류 내용</summary><pre>${escape(t.error)}</pre></details>`:''}</td><td>${escape(t.deps?.join(', ')||'—')}</td><td>${t.attempts}</td><td>${duration(t.estimate_s)}</td><td>${t.output?`<button data-tm-result="${escape(t.id)}" data-tm-attempt="${t.attempts}">결과 보기</button><a href="${escape(resultURL(t.id,t.attempts,'result.json'))}">JSON 저장</a>`:'—'}</td></tr>`).join('')}</tbody></table></div>`;
  }else if(model.tab==='attempts'){
    area.innerHTML=d.attempts.length?`<div class="tm-scroll"><table><tr><th>작업</th><th>시도</th><th>상태</th><th>시작 / 종료 (KST)</th><th>소요</th><th>기록</th></tr>${d.attempts.map(a=>`<tr><td>${escape(a.task_id)}</td><td>${a.number}</td><td>${badge(a.state)}</td><td>${escape(time(a.started))}<br>${escape(time(a.ended))}</td><td>${duration(a.ended?a.ended-a.started:null)}</td><td><a href="${escape(resultURL(a.task_id,a.number,'worker.log'))}">로그 저장</a><details><summary>저장 위치</summary><pre>${escape(a.output_dir)}</pre>${a.error?`<p class="error">${escape(a.error)}</p>`:''}</details></td></tr>`).join('')}</table></div>`:'<p class="tm-empty">아직 실행 이력이 없습니다.</p>';
  }else{
    const result=model.result;
    const files=result&&['spm-formula-result-v1','spm-job-result-v1'].includes(result.data.schema)?['result.json','inputs.csv','results.csv','motorcad.csv','worker.log']:['result.json','worker.log'];
    area.innerHTML=result?`<div class="tm-result"><h4>${escape(result.task)} · 시도 ${result.attempt}</h4><p>계산 결론: <strong>${escape(result.data.status||'결과 파일 참조')}</strong></p><p class="muted">이 표시와 작업 실행 완료는 모터 요구조건 합격을 보장하지 않습니다.</p><div class="tm-actions">${files.map(file=>`<a href="${escape(resultURL(result.task,result.attempt,file))}">${escape(file)} 저장</a>`).join('')}</div><p class="muted">해당 종류가 생성한 파일만 내려받을 수 있습니다.</p><details open><summary>저장된 결과</summary><pre id="tm-result-json">${escape(JSON.stringify(result.data,null,2))}</pre></details></div>`:'<p class="tm-empty">작업 목록의 ‘결과 보기’를 누르세요.</p>';
  }
}
function render(){renderNotices();renderList();renderDetail();for(const id of ['tm-refresh','tm-import','tm-create-formula','tm-create-verification','tm-create-mock'])node(id).disabled=model.busy;}
async function refresh(preferred=null){
  const token=++loadToken;
  const list=await api('/api/task-queue');if(token!==loadToken||!modal.open)return;
  model.jobs=list.jobs;
  const selected=preferred||model.selected||list.jobs[0]?.id;
  if(selected){
    const changed=selected!==model.selected;const detail=await api('/api/task-queue?id='+encodeURIComponent(selected));
    if(token!==loadToken||!modal.open)return;
    model.selected=selected;model.detail=detail;
    if(changed){model.native=false;model.reviewed=false;model.result=null;model.tab='tasks';model.retries.clear();}
    else model.retries=new Set([...model.retries].filter(id=>detail.tasks.some(t=>t.id===id&&t.state==='failed')));
  }else{model.detail=null;model.selected=null;}
  render();
}
async function action(fn){
  if(model.busy)return;model.busy=true;model.error='';render();
  try{await fn();}catch(error){model.error=errorText(error);}
  finally{model.busy=false;render();}
}
function schedule(){
  clearTimeout(timer);
  if(modal.open&&model.auto)timer=setTimeout(async()=>{
    if(!model.busy&&document.visibilityState==='visible')try{await refresh();}catch(error){model.error=errorText(error);renderNotices();}
    schedule();
  },5000);
}
async function register(title,tasks){
  const result=await api('/api/task-queue/create',{title,tasks});model.notice='계획을 등록했습니다. 시작 버튼을 누르기 전에는 계산하지 않습니다.';await refresh(result.id);
}
openButton.addEventListener('click',()=>{
  model.native=false;model.reviewed=false;modal.showModal();action(()=>refresh());schedule();
});
modal.addEventListener('close',()=>{clearTimeout(timer);loadToken++;model.native=false;model.reviewed=false;});
modal.addEventListener('change',event=>{
  const target=event.target;
  if(target.id==='tm-auto'){model.auto=target.checked;schedule();}
  if(target.id==='tm-native'){model.native=target.checked;renderDetail();}
  if(target.id==='tm-reviewed'){model.reviewed=target.checked;renderDetail();}
  if(target.dataset.tmRetry){target.checked?model.retries.add(target.dataset.tmRetry):model.retries.delete(target.dataset.tmRetry);model.reviewed=false;renderDetail();}
});
modal.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button)return;
  const id=button.id;
  if(id==='tm-close'){modal.close();return;}
  if(button.dataset.tmTab){model.tab=button.dataset.tmTab;renderDetail();return;}
  if(button.dataset.tmJob){action(()=>refresh(button.dataset.tmJob));return;}
  if(id==='tm-refresh'){action(()=>refresh());return;}
  if(id==='tm-import'){action(async()=>{const r=await api('/api/task-queue/import-checklist',{});model.notice='기존 검증 준비 항목을 가져왔습니다. 구체적인 실행 조건이 필요한 항목은 보류입니다.';await refresh(r.id);});return;}
  if(id==='tm-create-mock'){action(()=>register('모의 실패·재개 예제 · '+new Date().toLocaleTimeString('ko-KR'),[
    {id:'prepare',kind:'mock',payload:{value:'모의 준비',run:Date.now()},estimate_s:1},
    {id:'solve',kind:'mock',payload:{value:'모의 해석',fail_until_attempt:1},depends_on:['prepare'],estimate_s:1},
    {id:'compare',kind:'mock',payload:{value:'모의 비교'},depends_on:['solve'],estimate_s:1}
  ]));return;}
  if(id==='tm-create-formula'){action(async()=>{
    if(typeof toStudyRequest!=='function')throw Error('현재 입력을 읽을 수 없습니다.');
    await register('현재 입력 · 수식 최적화',[{id:'formula',kind:'formula',payload:{request:toStudyRequest()}}]);
  });return;}
  if(id==='tm-create-verification'){action(async()=>{
    const source=typeof formulaArchive!=='undefined'?formulaArchive:null;
    if(!source?.result||source.result.stage!=='formula')throw Error('설계안 비교에서 저장된 수식 결과를 먼저 열어 주세요.');
    const ids=selectedFormulaIds(source);if(!ids.length)throw Error('검증할 후보를 하나 이상 선택하세요.');
    const estimate=await api('/api/verification-estimate',{id:source.id,selected_model_ids:ids});
    const tasks=ids.map((ident,index)=>({id:'verify_'+index,kind:'motorcad_verify',
      payload:{request:{...structuredClone(source.result.request),formula_source_job:source.id,selected_model_ids:[ident],open_motorcad_after:false}},
      ...(estimate.estimated_max_s?{estimate_s:estimate.estimated_max_s/ids.length}:{})}));
    await register('선택 후보 검증 · '+source.id,tasks);
  });return;}
  if(['tm-start','tm-resume','tm-retry'].includes(id)){action(async()=>{
    const result=await api('/api/task-queue/start',{id:model.selected,allow_native:model.native,resume:id!=='tm-start',retry_ids:id==='tm-retry'?[...model.retries]:[],reviewed:model.reviewed});
    model.notice=`백그라운드 시작 요청을 보냈습니다. 작업 프로세스 ${result.worker_pid}. 다음 새로고침에서 진행 상태를 확인하세요.`;
    await refresh();
  });return;}
  if(id==='tm-stop'){action(async()=>{await api('/api/task-queue/stop',{id:model.selected});model.notice='중단을 요청했습니다. 완료 결과는 보존하고 지원되는 다음 경계에서 멈춥니다.';await refresh();});return;}
  if(button.dataset.tmResult){action(async()=>{
    const task=button.dataset.tmResult,attempt=Number(button.dataset.tmAttempt);
    const data=await api(resultURL(task,attempt,'result.json'));model.result={task,attempt,data};model.tab='result';
  });}
});
render();
