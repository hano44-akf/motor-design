/* Optimize first, review/exclude candidates, then explicitly start selected FEA. */
let formulaArchive=null,verificationEstimate=null,localStageRunning=false;
function selectedFormulaIds(job){
  state.formulaSelections=state.formulaSelections||{};
  if(!Array.isArray(state.formulaSelections[job.id]))state.formulaSelections[job.id]=job.result.results.map(c=>c.id);
  return state.formulaSelections[job.id];
}
function secondsLabel(v){return Number.isFinite(v)?`${v.toFixed(1)}초 (${(v/60).toFixed(1)}분)`:'자료 없음';}
function formulaRequirementReview(r){
  const margin=r.request.operating_point.torque_margin_pct||0;
  const marginNote=margin>0?`<p>토크 여유 ${esc(margin)}%는 정격 목표를 바꾸지 않는 별도 능력 요구입니다. 여유 능력점은 아직 미검증이며 정격점 결과로 만족 처리하지 않습니다.</p>`:'';
  const rows=r.results.map(c=>{
    const review=c.formula_review,p=c.prediction;
    const dc=Number.isFinite(p.estimated_dc_current_A)?p.estimated_dc_current_A.toFixed(3)+' A':'미계산';
    const limit=r.request.operating_point.dc_current_max_A;
    const dcState=limit==null?'목표 제외':p.dc_current_requirement_state==='predicted_unmet'?'예측 미달':p.dc_current_requirement_state==='predicted_met'?'예측 범위 내':'미계산';
    const state=review?.predicted_all_active_met===false?'알려진 예측 위반 있음':review?.predicted_all_active_met===true?'예측상 만족 · FEA 전':'미검증 요구 있음';
    return `<tr><td>${esc(c.id)}</td><td>${dc}</td><td>${limit==null?'공란':esc(limit)+' A'} / ${dcState}</td><td>${state}</td></tr>`;
  }).join('');
  return panel('요구조건별 예측·미검증',`<div id="formula-requirements">${marginNote}<div class="scroll"><table><tr><th>모델</th><th>DC 평균전류 예측</th><th>DC 상한 / 예측 판정</th><th>전체 요구</th></tr>${rows}</table></div><p>DC 전류는 모터 입력전력 기준이며 인버터 효율 100%를 가정합니다. 인버터 손실은 포함하지 않습니다. 효율 공란은 목표에서 제외합니다.</p><p>모델 정확도의 유효 범위는 미검증입니다. 수식은 기준 온도·최소 버스 조건을 평가하며 B·토크 리플·PWM 및 나머지 온도·전압 조건은 미검증으로 남습니다. 수식 스크린 통과는 전체 요구 합격을 뜻하지 않습니다.</p></div>`);
}
function formulaResults(job){
  formulaArchive=job;const r=job.result,s=r.search_statistics,ids=selectedFormulaIds(job);
  return formulaRequirementReview(r)+'<div class="result-note">수식 최적화 완료 · PyMotorCAD 해석 0회. 후보를 비교하고 제외한 뒤 선택한 모델만 검증하세요. 아래 효율·전압은 저장된 기준 해석으로 보정한 근사 예측이며 B·리플 합격을 의미하지 않습니다.</div>'+
    panel('이 최적화에 사용한 입력',`<p>${esc(r.request.core)} / ${esc(r.request.magnet)} · ${esc(r.request.operating_point.torque_Nm)} N·m / ${esc(r.request.operating_point.speed_rpm)} rpm · 버스 ${esc(r.request.operating_point.voltages_V.join(', '))} V · 기준 ${esc(r.request.temperatures_C[0])}°C</p><p>Surface ${esc(r.request.spm.shape)} / ${esc(r.request.spm.magnetisation)} 착자 · ${esc(r.operating_policy.current_control)} / 약계자 ${r.operating_policy.field_weakening?'허용':'금지'} · 에어갭 ${esc(r.effective_airgap_bounds_mm.join('~'))} mm</p><p class="muted">저장된 입력 기준입니다. 화면 입력을 바꿔도 이 결과는 바뀌지 않습니다.</p>`)+
    panel('최적화 시간 · 파라미터 수',`<div class="metrics"><div class="metric"><small>최적화 계산 시간</small><b>${r.timings.optimization_compute_s.toFixed(3)}초</b></div><div class="metric"><small>독립 / 자유 설계 변수</small><b>${s.design_dimensions} / ${s.free_design_dimensions}</b></div><div class="metric"><small>고유 검토 조합</small><b>${s.unique_design_points.toLocaleString()}</b></div></div><p>전체 격자 가능 조합 ${s.full_grid_combinations.toLocaleString()}개 / 실제 목적함수 호출 ${s.objective_evaluations.toLocaleString()}회 / 전류각 전수 스윕 없음 / 신규 Motor-CAD 해석 0회</p><p class="muted">형상은 외경·적층·턴·선경·에어갭입니다. 전류·전류각은 각 후보의 요구 부하에서 계산하는 내부 운전 변수입니다. 현재 엔진은 차분진화 + 국소 근사 모델입니다.</p>`)+
    panel('수식 설계안 비교 · 검증할 모델 선택',`<div class="scroll"><table><tr><th>검증</th><th>모델 / 목적</th><th>철심 외경 mm</th><th>적층 mm</th><th>턴</th><th>선경 mm</th><th>에어갭 mm</th><th>효율 예측 %</th><th>전류 진각 °</th><th>수식 스크린</th></tr>${r.results.map(c=>`<tr><td><input type="checkbox" data-formula-model="${esc(c.id)}" ${ids.includes(c.id)?'checked':''} aria-label="${esc(c.id)} 검증 선택"></td><td>${esc(c.id)} / ${esc(c.objective)}</td><td>${c.design.diameter_mm}</td><td>${c.design.length_mm}</td><td>${c.design.turns_per_coil}</td><td>${c.design.wire_diameter_mm}</td><td>${c.design.airgap_mm}</td><td>${c.prediction.efficiency_pct.toFixed(3)}</td><td>${c.design.phase_advance_deg.toFixed(3)}</td><td>${c.physical_screens_pass?'통과 · FEA 전':'미달 진단 후보'}</td></tr>`).join('')}</table></div>`)+
    panel('수식 계산 상세',r.results.map(c=>`<details><summary>${esc(c.id)} · 저항·역기전력·손실·전류·제어점·형상</summary><div class="scroll"><table><tr><th>항목</th><th>예측값 / 기준</th></tr>${csvFlatten({design:c.design,prediction:c.prediction}).map(([key,value])=>`<tr><td>${esc(key)}</td><td>${esc(value)}</td></tr>`).join('')}</table></div></details>`).join(''))+
    panel('선택 모델 PyMotorCAD 해석',`<p>해석할 모델 수: <b id="verification-model-count">${ids.length}</b> / ${r.results.length}</p><p id="verification-estimate">모델 수에 따른 소요 시간 계산 중…</p><button class="primary" id="start-selected-verification" ${ids.length?'':'disabled'}>선택 모델 PyMotorCAD 해석 시작</button><p id="verification-status" role="status">제외할 모델의 체크를 해제하세요. 이 버튼을 누르기 전에는 Motor-CAD가 실행되지 않습니다.</p><p class="muted">예상 시간은 과거 해석 기록을 사용하며 시작/재질 준비·실패 재시도는 별도입니다. 해석 후 필요 전류·각도를 보정할 수 있지만 선택 형상·턴·선경·에어갭은 유지합니다.</p>`);
}
const resultsBeforeStagedWorkflow=results;
results=function(){
  if(realJob&&['failed','cancelled'].includes(realJob.progress?.status))return panel('계산 종료',`<p id="pipeline-error">${esc(realJob.error?.error||realJob.progress.error||realJob.progress.status)}</p><p>완료된 파일은 보존됩니다. 수식 최적화 버튼에서 입력을 확인한 뒤 다시 실행할 수 있습니다.</p>`);
  if(localStageRunning&&!realJob?.result)return panel('계산 진행 중','<p>로컬 Python 계산을 진행하고 있습니다. 완료되면 결과와 소요 시간·검토 조합 수를 표시합니다.</p><p class="muted">수식 최적화에서는 Motor-CAD를 실행하지 않습니다. 선택 모델 검증을 시작한 경우에만 해석합니다.</p>');
  if(realJob?.result?.stage==='formula')return formulaResults(realJob);
  let html=resultsBeforeStagedWorkflow();
  if(realJob?.result?.stage==='verification'){
    const r=realJob.result;
    html=panel('선택 모델 해석 소요 시간',`<p>수식 최적화 ${r.timings.optimization_compute_s.toFixed(3)}초 / 선택 모델 ${r.results.length}개 / 이번 검증 총 경과 ${secondsLabel(r.timings.session_wall_s)} / 실제 솔버 호출 ${r.timings.recorded_solve_count}회</p>`)+html;
    html+=panel('수식 예측과 PyMotorCAD 비교',`<div class="scroll"><table><tr><th>모델</th><th>수식 효율 %</th><th>FEA 조건</th><th>FEA 효율 %</th><th>축토크 Nm</th><th>리플 %</th></tr>${r.results.map(c=>c.runs.map(x=>`<tr><td>${esc(c.id)}</td><td>${x.verification_role==='capacity'?'-':c.prediction.efficiency_pct.toFixed(3)}</td><td>${x.verification_role==='capacity'?'\uC5EC\uC720\uC810':'\uC815\uACA9\uC810'} / ${esc(x.input_options.temperature_C)}°C / ${esc(x.design.voltage_V)} V</td><td>${x.values['System Efficiency']}</td><td>${x.values['Shaft Torque']}</td><td>${x.values['Torque Ripple (MsVw) [%]']}</td></tr>`).join('')).join('')}</table></div><p class="muted">수식 예측은 기준 온도·최소 버스 조건입니다. 다른 온도/전압의 FEA와는 조건 차이를 함께 확인하세요.</p>`);
  }
  return html;
};
async function refreshVerificationEstimate(){
  if(!formulaArchive||!$('#verification-estimate'))return;
  const job=formulaArchive,ids=selectedFormulaIds(job),target=$('#verification-estimate');
  $('#verification-model-count').textContent=ids.length;$('#start-selected-verification').disabled=!ids.length;
  if(!ids.length){target.textContent='모델을 하나 이상 선택하세요.';return;}
  try{
    const response=await fetch('/api/verification-estimate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:job.id,selected_model_ids:ids})});
    const data=await response.json();if(!response.ok)throw Error(data.error);verificationEstimate=data;
    if($('#verification-estimate')!==target)return;
    target.textContent=`예상 ${secondsLabel(data.estimated_min_s)} ~ ${secondsLabel(data.estimated_max_s)} · ${data.models}모델 × ${data.conditions_per_model} (nominal ${data.nominal_conditions_per_model??data.conditions_per_model}, capacity ${data.capacity_conditions_per_model??0})조건 · 기본 ${data.base_solves}회, 전류 보정 포함 최대 ${data.max_solves_with_corrections}회`;
  }catch(e){target.textContent='예상 시간 조회 실패: '+e.message;}
}
$('#engine-start').textContent='현재 입력으로 수식 최적화';$('#engine-open').textContent='수식 최적화';
engineDialog.querySelectorAll('p')[1].textContent='수식 최적화는 형상·착자별 저장 기준 해석을 재사용합니다. 기준 20°C Radial/Radial 또는 Parallel/Parallel을 지원합니다. 결과창에서 모델을 선택한 뒤 검증 버튼을 눌러야 새 PyMotorCAD 해석을 시작합니다.';
$('#engine-start').onclick=async()=>{
  try{
    if(!localEngine)throw Error('로컬 Python 서버를 연결하세요.');
    const request=toStudyRequest();const response=await fetch('/api/optimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    const data=await response.json();if(!response.ok)throw Error(data.error);
    jobId=data.id;realJob=null;formulaArchive=null;localStageRunning=true;localStorage.setItem('motor-active-job',jobId);
    $('#engine-downloads').innerHTML='';$('#engine-status').textContent='수식 최적화 시작 · Motor-CAD 해석은 실행하지 않습니다.';
    state.page=4;engineDialog.close();render();await pollJob();
  }catch(e){$('#engine-status').textContent='실행 불가: '+e.message;}
};
document.addEventListener('change',e=>{
  if(!e.target.dataset.formulaModel)return;
  const ids=selectedFormulaIds(formulaArchive),id=e.target.dataset.formulaModel;
  state.formulaSelections[formulaArchive.id]=e.target.checked?[...new Set([...ids,id])]:ids.filter(x=>x!==id);
  persist();refreshVerificationEstimate();
},true);
document.addEventListener('click',async e=>{
  if(!e.target.closest('#start-selected-verification'))return;
  const b=$('#start-selected-verification'),status=$('#verification-status');b.disabled=true;
  try{
    const response=await fetch('/api/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:formulaArchive.id,selected_model_ids:selectedFormulaIds(formulaArchive),open_motorcad_after:state.openMotorcadAfter===true})});
    const data=await response.json();if(!response.ok)throw Error(data.error);
    jobId=data.id;localStageRunning=true;realJob=null;localStorage.setItem('motor-active-job',jobId);status.textContent='선택 모델 해석 대기 중…';render();await pollJob();
  }catch(e){status.textContent='해석 시작 실패: '+e.message;b.disabled=false;}
});
const renderBeforeStagedWorkflow=render;
render=function(){
  renderBeforeStagedWorkflow();
  if(realJob?.result?.stage==='formula'&&state.page===4){$('#subtitle').textContent='수식 최적화 결과를 비교하고 선택 모델만 PyMotorCAD로 검증합니다.';refreshVerificationEstimate();}
};
const reviewBeforeWorkflowStats=review;
review=function(){
  reviewBeforeWorkflowStats();
  try{
    const request=toStudyRequest(),bounds=[...request.bounds,request.airgap_bounds_mm];
    const counts=bounds.map(([lo,hi],i)=>Math.floor(hi*(i===2?1:10)+1e-8)-Math.ceil(lo*(i===2?1:10)-1e-8)+1);
    const last=realJob?.result?.timings?.optimization_compute_s;
    $('#reviewbody').insertAdjacentHTML('beforeend',`<p>독립 설계 항목 5개 / 자유 변수 ${counts.filter(n=>n>1).length}개 / 전체 격자 조합 ${counts.reduce((a,b)=>a*b,1).toLocaleString()}개</p><p>직전 최적화 시간: ${last===undefined?'미실행':last.toFixed(3)+'초'} · 이번 실제 평가 횟수와 시간은 실행 후 표시합니다. 전류각 격자는 추가하지 않습니다.</p>`);
  }catch(e){$('#reviewbody').insertAdjacentHTML('beforeend',`<p class="muted">탐색 규모는 지원 입력이 완성되면 계산합니다: ${esc(e.message)}</p>`);}
};
$('#review').onclick=review;
// Display live elapsed time outside re-rendered result content.
const progressPanel=document.createElement('section');progressPanel.id='calculation-progress';progressPanel.className='notice';progressPanel.hidden=true;
document.querySelector('.workspace').append(progressPanel);
setInterval(()=>{
  const p=realJob?.progress;if(!p||['completed','failed','cancelled'].includes(p.status)){progressPanel.hidden=true;if(p&&['failed','cancelled'].includes(p.status)&&state.page===4&&!$('#pipeline-error'))render();return;}
  progressPanel.hidden=false;const elapsed=p.started_unix?Date.now()/1000-p.started_unix:p.elapsed_s;
  progressPanel.textContent=`계산 진행 · ${p.status} · 경과 ${secondsLabel(elapsed)} · 선택 모델 ${p.selected_models??'—'}개 / 완료 ${p.completed_models??0}개 · 해석 호출 ${p.solves_this_session??0}회`;
},500);
render();
