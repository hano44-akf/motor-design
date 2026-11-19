/* Read-only requirement review. No optimization or native execution calls. */
const labels={passed:'만족',violated:'불만족',unverified:'미검증',not_applicable:'목표 제외',requirements_passed:'요구조건 만족',requirements_violated:'요구조건 불만족',verification_incomplete:'검증 미완료'};
const names={capacity_torque_Nm:'\uC5EC\uC720 \uD1A0\uD06C (Nm)',torque_Nm:'최소 토크 (Nm)',efficiency_pct:'최소 효율 (%)',torque_ripple_max_pct:'최대 토크 리플 (%)',flux_density_max_T:'철심 최대 B (T)',current_density_max_A_mm2:'최대 전류밀도 (A/mm²)',dc_current_max_A:'최대 DC 전류 (A)',pwm_current_ripple:'PWM 전류 리플',iron_flux_density:'철심 영역별 B 확인',nonlinear_control_optimality:'비선형 제어점 최적성',demagnetization_under_negative_Id:'음의 Id 감자'};
const escapeHtml=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>typeof v==='number'&&Number.isFinite(v)?(Number.isInteger(v)?v:Number(v.toPrecision(6))).toLocaleString('ko-KR',{maximumFractionDigits:6}):'—';
const cache=new Map();let pending='';
function badge(state){return `<span class="rr-state rr-${state}">${escapeHtml(labels[state]||state)}</span>`;}
function renderReview(r){
 const t=r.timings,s=r.search_statistics;
 return `<h2>요구조건 판정 · 상세 비교</h2><p>저장된 입력으로 현재 판정 규칙을 적용했습니다. 새 해석 0회이며, 원본 결과는 보존합니다.</p>
 <p>${r.best_available?`검사 통과 후보 중 잠정 최선: <b>${escapeHtml(r.best_available)}</b>`:r.best_diagnostic?`전압·형상 검사 통과 후보 없음 · 진단용 비교 대상: <b>${escapeHtml(r.best_diagnostic)}</b>`:'수식 예측 단계 · FEA 검증 전'}</p>
 <p class="muted">잠정 최선은 설계 승인과 다릅니다. 불만족 후보끼리는 최악 운전조건의 정규화 부족분을 먼저 비교하고, 미검증 개수를 별도로 표시합니다.</p>
 <div class="scroll"><table><tr><th>최적화 시간 s</th><th>검증 실행 경과 s</th><th>솔버 호출</th><th>목적함수 평가</th><th>고유 설계점</th><th>전체 격자 조합</th></tr><tr><td>${num(t.optimization_compute_s)}</td><td>${r.stage==='formula'?'—':num(t.session_wall_s)}</td><td>${num(t.recorded_solve_count)}</td><td>${num(s.objective_evaluations)}</td><td>${num(s.unique_design_points)}</td><td>${num(s.full_grid_combinations)}</td></tr></table></div>
 ${r.candidates.map(c=>`<article class="rr-candidate"><h3>${escapeHtml(c.id)} · ${badge(c.status)}</h3>
 <p>정규화한 알려진 부족분: ${num(c.worst_known_normalized_shortfall)} · 미검증 항목 ${c.runs.length?c.runs.reduce((n,x)=>n+x.requirement_summary.unverified.length,0):'확인 전'}</p>
 ${c.runs.length?c.runs.map(run=>`<details open><summary>${run.verification_role==='capacity'?'\uC5EC\uC720\uC810':'\uC815\uACA9\uC810'} / ${escapeHtml(run.label)} · ${num(run.temperature_C)}℃ / ${num(run.voltage_V)}V · 축토크 ${num(run.torque_Nm)} Nm</summary>
 <p>전압·형상 검사: ${run.physical_screens_pass?'통과':'미통과'} · ${badge(run.requirement_summary.status)}</p>
 <div class="scroll"><table><tr><th>요구조건</th><th>상태</th><th>요구값</th><th>해석값</th><th>부족·초과량</th></tr>${run.requirements.map(q=>`<tr><td>${escapeHtml(names[q.id]||q.id)}</td><td>${badge(q.state)}</td><td>${q.evidence_only?'별도 확인 필요':num(q.limit)}</td><td>${num(q.actual)}</td><td>${num(q.shortfall)}</td></tr>`).join('')}</table></div>
 <details><summary>전압·형상 검사 세부</summary><ul>${run.physical_screens.map(q=>`<li>${escapeHtml(q.id)}: ${badge(q.state)}</li>`).join('')}</ul></details>
 <div class="scroll"><table><tr><th>항목</th><th>수식 예측</th><th>FEA</th><th>FEA−예측</th></tr>${run.metrics.map(m=>`<tr><td>${escapeHtml(m.label)} (${escapeHtml(m.unit)})</td><td>${num(m.prediction)}</td><td>${num(m.actual)}</td><td>${num(m.difference)}</td></tr>`).join('')}</table></div>
 <p class="muted">온도·버스 조건이 다르면 차이를 계산하지 않습니다. 같은 조건도 FEA 전류 보정에 따른 차이가 포함될 수 있습니다.</p>
 <details><summary>형상 치수 · 적용 파일 · 해석 시간</summary><p class="rr-path">${escapeHtml(run.model_path||'저장 모델 파일 없음')}</p><p>솔버 ${num(run.timings.solver_s)}초 / 준비·저장 포함 ${num(run.timings.total_s)}초</p><div class="scroll"><table>${Object.entries(run.geometry_mm).map(([k,v])=>`<tr><td>${escapeHtml(k)}</td><td>${num(v)} mm</td></tr>`).join('')}</table></div></details>
 </details>`).join(''):'<p>수식 예측만 있습니다. 토크 리플·B·PWM 등 FEA 및 별도 검증 항목을 만족으로 처리하지 않습니다.</p>'}</article>`).join('')}`;
}
const style=document.createElement('style');style.textContent='.rr-candidate{border-top:1px solid #cbd5e1;margin-top:16px;padding-top:8px}.rr-state{display:inline-block;padding:2px 7px;border-radius:4px;font-size:12px;background:#e2e8f0}.rr-passed,.rr-requirements_passed{background:#dcfce7;color:#166534}.rr-violated,.rr-requirements_violated{background:#fee2e2;color:#991b1b}.rr-unverified,.rr-verification_incomplete{background:#fef3c7;color:#854d0e}.rr-path{overflow-wrap:anywhere}#result-requirement-review{max-width:100%;min-width:0}#result-requirement-review details{margin:10px 0}';document.head.append(style);
async function refresh(){
 const content=document.querySelector('#content');
 if(typeof realJob==='undefined'||!realJob?.result||typeof state==='undefined'||state.page!==4)return;
 const id=realJob.id;
 if(document.querySelector('#result-requirement-review')?.dataset.job===id)return;
 if(pending===id)return;
 let data=cache.get(id);
 if(!data){pending=id;try{const response=await fetch('/api/result-review?id='+encodeURIComponent(id));data=await response.json();if(!response.ok)throw Error(data.error||'판정 조회 실패');cache.set(id,data);}catch(error){data={error:error.message};cache.set(id,data);}finally{pending='';}}
 if(realJob?.id!==id||state.page!==4)return;
 const section=document.createElement('section');section.id='result-requirement-review';section.className='panel';section.dataset.job=id;
 section.innerHTML=data.error?`<h2>상세 판정 조회 실패</h2><p>${escapeHtml(data.error)}</p>`:renderReview(data);
 document.querySelector('#result-requirement-review')?.remove();content.prepend(section);
}
new MutationObserver(refresh).observe(document.querySelector('#content'),{childList:true});refresh();
