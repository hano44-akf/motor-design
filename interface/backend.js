/* Local Python execution and persisted real results; synthetic examples remain separate. */
let realJob=null,jobId=new URLSearchParams(location.search).get('job')||localStorage.getItem('motor-active-job')||'',localEngine=false;
const persistBeforeEngine=persist;
persist=function(){persistBeforeEngine();if(localEngine)$('#status').textContent='설정 자동 저장됨 · 로컬 Python 연결됨';};
function toStudyRequest(){
  const has=v=>v!==''&&v!==undefined&&v!==null;
  if(state.ops.length!==1)throw Error('첫 자동 실행 버전은 운전점 1개를 지원합니다.');
  if(state.core.length!==1||state.core[0]!=='50PN470'||state.grades.length!==1||Number(state.grades[0])!==48||state.suffix.length!==1||state.suffix[0]!=='UH')throw Error('첫 자동 실행 버전에서는 50PN470 / N48UH를 각각 단독 선택하세요.');
  if(!state.control.startsWith('FOC')||state.modulation!=='SVPWM')throw Error('현재 자동 실행은 FOC / SVPWM을 지원합니다.');
  if(has(state.eta)&&Number(state.eta)!==100||has(state.mechanical)&&Number(state.mechanical)!==0)throw Error('현재 자동 실행은 제어 효율 100%, 기계 손실 0 W 기준입니다.');
  const supported=['od','length','turns','wire','poles','slots','strands','paths','gap'];
  for(const [label,k] of geom)if(!supported.includes(k)&&mode(k)!=='auto')throw Error(label+': 현재 자동 실행 형상에서는 자동 비례 치수만 지원합니다.');
  for(const [k,n] of [['poles',4],['slots',12],['strands',1],['paths',1]]){
    if(['poles','slots'].includes(k)&&Array.isArray(state.poleSlotCandidates))continue;
    if(mode(k)!=='auto'&&(mode(k)!=='fixed'||Number(state.geometry[k])!==n))throw Error(`${k}: 현재 자동 실행은 ${n} 고정입니다.`);
  }
  if((state.connection||'delta')!=='delta')throw Error('현재 자동 실행은 Delta 결선입니다.');
  if(state.priority==='경량화')throw Error('현재 자동 실행에는 전체 질량 모델이 연결되지 않았습니다. 소형화·균형형·고효율 중 선택하세요.');
  if(Number(state.margin||0)<0)throw Error('토크 마진은 0% 이상이어야 합니다.');
  const scale=unitChoices.length.options[state.units];
  const bounds=[['od',[55,100]],['length',[20,65]],['turns',[1,8]],['wire',[.8,2.2]]].map(([k,base])=>{
    const f=k==='turns'?1:scale,m=mode(k);
    return m==='auto'?base:m==='fixed'?[state.geometry[k]*f,state.geometry[k]*f]:[state.ranges[k]?.min*f,state.ranges[k]?.max*f];
  });
  const o=state.ops[0];
  if(!(o.torque>0&&o.rpm>0))throw Error('이번 자동 실행에는 양수 토크와 RPM이 필요합니다.');
  const voltages=['vmin','vrated','vmax'].filter(k=>has(o[k])).map(k=>o[k]);
  if(!voltages.length)throw Error('DC 전압을 하나 이상 입력하세요.');
  if(has(o.vmin)&&has(o.vrated)&&o.vmin>o.vrated||has(o.vrated)&&has(o.vmax)&&o.vrated>o.vmax||has(o.vmin)&&has(o.vmax)&&o.vmin>o.vmax)throw Error('DC 전압 최소 ≤ 정격 ≤ 최대를 확인하세요.');
  return {schema:'spm-study-v1',core:'POSCO | 50PN470',magnet:'JL Mag Rare-Earth | N48UH',spm:{...state.spm},connection:'delta',strands:1,paths:1,control:'FOC_Id0_SVPWM',temperatures_C:[...new Set(['temp','tmin','tmax'].filter(k=>has(state[k])).map(k=>Number(state[k])))],operating_point:{torque_Nm:o.torque,torque_margin_pct:Number(state.margin||0),speed_rpm:o.rpm,efficiency_min_pct:has(o.eff)?o.eff:null,voltages_V:[...new Set(voltages)],dc_current_max_A:has(o.imax)?o.imax:null,current_density_max_A_mm2:has(o.density)?o.density:null,torque_ripple_max_pct:has(o.ripple)?o.ripple:null},selection_priority:{'균형형':'balanced','소형화':'compact','고효율':'efficient'}[state.priority]||'balanced',ui_input_snapshot:structuredClone(state),bounds,search_rounds:2};
}
function actualResults(){
  const r=realJob.result;
  const title={target_met:'목표 만족 후보 확보',verification_incomplete:'검증 가능한 목표 만족 · PWM 검증 미완료',best_effort:'목표 미달 · 최선 후보 반환',no_screened_candidate:'물리 제약 검사 통과 후보 없음'}[r.status]||r.status;
  let html=`<div class="result-note">실제 PyMotorCAD 해석 결과 · 작업 ${esc(realJob.id)} · ${esc(title)}<br>아래 값은 이 작업에 저장된 입력 기준입니다. 현재 화면에서 입력을 바꿔도 과거 결과는 바뀌지 않습니다.</div>`;
  html+=panel('해석에 사용한 입력',`<p>${esc(r.request.core)} / ${esc(r.request.magnet)} / ${esc(r.request.spm.shape)} / ${esc(r.request.spm.magnetisation)} 착자</p><p>목표 ${esc(r.request.operating_point.torque_Nm)} N·m / ${esc(r.request.operating_point.speed_rpm)} rpm / 효율 ${esc(r.request.operating_point.efficiency_min_pct??'목표 제외')}% · 전압 ${esc(r.request.operating_point.voltages_V.join(', '))} V</p>`);
  for(const c of r.results){
    html+=panel(`${esc(c.id)} · ${c.target_met?'목표 만족':c.physical_screens_pass?'목표 미달':'전압·형상 등 검사 미통과'}`,`<p>외경 ${esc(c.design.diameter_mm)} mm / 적층 ${esc(c.design.length_mm)} mm / ${esc(c.design.turns_per_coil)}턴 / 선경 ${esc(c.design.wire_diameter_mm)} mm / 선전류 첨두 ${esc(c.design.input_peak_current_A.toFixed(3))} A</p><div class="scroll"><table><tr><th>온도 / DC</th><th>토크 N·m</th><th>효율 %</th><th>선간 피크 V</th><th>판정 / 부족분</th></tr>${c.runs.map(x=>`<tr><td>${esc(x.input_options.temperature_C)}℃ / ${esc(x.design.voltage_V)} V</td><td>${esc(x.values['Shaft Torque'])}</td><td>${esc(x.values['System Efficiency'])}</td><td>${esc(x.values['Line-Line Terminal Voltage (peak)'])}</td><td>${esc(x.values['Torque Ripple (MsVw) [%]'])}</td><td>${esc(x.assessment.target_met?'목표 만족':JSON.stringify(x.assessment.shortfalls))}${x.assessment.physical_screens_pass?'':' / 물리 제약 검사 미통과'}</td></tr>`).join('')}</table></div><details><summary>저항 · 인덕턴스 · 역기전력 등 전체 결과 / 형상 · 적용값</summary><div class="scroll"><table><tr><th>해석</th><th>항목</th><th>값</th></tr>${c.runs.map(x=>csvFlatten({values:x.values,geometry_mm:x.geometry_mm,derived_lengths_mm:x.derived_lengths_mm,readback:x.readback,prediction:c.prediction}).map(([k,v])=>`<tr><td>${esc(x.label)}</td><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join('')).join('')}</table></div></details>`);
  }
  html=html.replaceAll('<th>선간 피크 V</th>','<th>선간 피크 V</th><th>토크 리플 %</th>');
  html+=panel('소요시간 및 검토 범위',`<p>이번 실행·재개 처리 ${esc(r.timings.session_wall_s.toFixed(1))}초 (완료된 해석은 재사용)<br>최종 모델의 해석 계산 합계 ${esc(r.timings.final_solver_sum_s.toFixed(1))}초 / 저장된 전체 탐색·보정 해석 ${esc((r.timings.all_recorded_solver_s||r.timings.final_solver_sum_s).toFixed(1))}초</p><ul>${['지정한 형상·범위·평가 예산에서 찾은 후보입니다.','50PN470의 50/60 Hz 외 철손은 외삽값입니다.','부품의 동일 온도를 지정하며, 기계 손실 0 W·이상 인버터 기준입니다.','전압 수치 검사만으로 스위칭 회로·Delta 순환전류를 검증하지는 않습니다.','토크 리플 상한이 공란이면 리플이 높아도 목표 미달로 판정하지 않습니다.'].map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`);
  if(r.effective_torque_ripple_limit_pct!==undefined)html=html.replace('토크 리플 상한이 공란이면 리플이 높아도 목표 미달로 판정하지 않습니다.',`이 작업의 토크 리플 상한은 ${r.effective_torque_ripple_limit_pct}%입니다. 초과 모델은 목표 미달로 표시합니다.`);
  if(r.review_only)html='<div class="notice">저장된 해석 결과를 새 요구조건으로 재판정했습니다. 추가 Motor-CAD 해석은 0회이며, 원본 작업은 보존했습니다.</div>'+html;
  if(r.effective_pwm_current_ripple_max_pct!==undefined)html='<div class="notice">허용 PWM 전류 리플 '+esc(r.effective_pwm_current_ripple_max_pct)+'%는 아직 파형 검증 전입니다. 미검증 항목을 만족한 것으로 처리하지 않습니다.</div>'+html;
  for(const c of r.results)if(c.known_targets_met&&!c.target_met)html=html.replace(`${esc(c.id)} · 목표 미달`,`${esc(c.id)} · 검증 미완료`);
  return html;
}
const exampleResults=results;
results=function(){return realJob?.result?actualResults():exampleResults();};
const engineDialog=document.createElement('dialog');engineDialog.id='engine-dialog';engineDialog.style.width='min(760px,94vw)';
engineDialog.innerHTML='<h2>Python 자동 설계 · PyMotorCAD 검증</h2><p>첫 연결 범위: 50PN470 / N48UH, 4극 12슬롯, Delta, 1가닥·1병렬, FOC Id=0 / SVPWM. 형상·착자별 새 기준 해석 후 탐색합니다.</p><p>운전점 1개와 입력된 기준·최소·최대 온도, DC 전압 최소·정격·최대를 검증합니다. 미지원 조건은 실행 전에 표시합니다.</p><p id="engine-status" aria-live="polite">연결 확인 중</p><button id="engine-example">기존 12V 사양 불러오기</button> <button id="engine-start" class="primary">현재 입력으로 자동 실행</button> <button id="engine-cancel">중지 요청</button><p id="engine-progress"></p><div id="engine-downloads"></div><button id="engine-show">저장 결과 보기</button> <button id="engine-close">닫기</button>';
document.body.append(engineDialog);
const engineButton=document.createElement('button');engineButton.id='engine-open';engineButton.textContent='실제 자동 설계';$('.toolbar').append(engineButton);
engineButton.onclick=()=>engineDialog.showModal();$('#engine-close').onclick=()=>engineDialog.close();
$('#engine-example').onclick=()=>{
  state.core=['50PN470'];state.grades=[48];state.suffix=['UH'];state.spm={shape:'Radial',magnetisation:'Radial'};state.geometry={poles:4,slots:12,strands:1,paths:1};state.modes={};state.ranges={};state.connection='delta';state.control='FOC · Id = 0';state.modulation='SVPWM';state.eta=100;state.mechanical=0;state.margin=0;state.temp=20;state.tmin='';state.tmax='';state.ops=[{vmin:9,vrated:12,vmax:16,torque:.5,rpm:3500,eff:88}];state.activeOp=0;persist();render();$('#engine-status').textContent='기존 사양을 입력했습니다. 실행 버튼으로 계산을 시작하세요.';
};
$('#engine-show').onclick=()=>{state.page=4;render();engineDialog.close();};
$('#engine-start').onclick=async()=>{
  try{if(!localEngine)throw Error('interface/launch.ps1로 로컬 서버를 실행하고 http://127.0.0.1:8765로 접속하세요.');const request=toStudyRequest();const response=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});const data=await response.json();if(!response.ok)throw Error(data.error);jobId=data.id;realJob=null;$('#engine-downloads').innerHTML='';localStorage.setItem('motor-active-job',jobId);$('#engine-status').textContent='작업 시작: '+jobId;await pollJob();}catch(e){$('#engine-status').textContent='실행 불가: '+e.message;}
};
$('#engine-cancel').onclick=async()=>{if(!jobId||!localEngine)return;await fetch('/api/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:jobId})});$('#engine-status').textContent='현재 해석이 끝난 뒤 중지합니다.';};
async function pollJob(){
  if(!localEngine||!jobId)return;
  try{const response=await fetch('/api/job?id='+encodeURIComponent(jobId));if(!response.ok)return;const data=await response.json();const wasComplete=!!realJob?.result;realJob=data;const p=data.progress;
    const stages={queued:'대기',starting:'시작',preparing_materials:'재질 준비',optimizing:'후보 탐색',solving:'Motor-CAD 해석',completed:'완료',failed:'오류 종료',cancelled:'중지'};
    $('#engine-progress').textContent=`작업 ${jobId} · ${stages[p.status]||p.status} · ${p.label||''} · ${p.events?.at(-1)?.elapsed_s?.toFixed(1)||0}초 (마지막 갱신)`;
    if(data.error)$('#engine-status').textContent='작업 종료: '+data.error.error;
    if(data.result){$('#engine-downloads').innerHTML=['inputs.csv','results.csv','motorcad.csv','result.json'].map(name=>`<p><a href="/api/download/${esc(jobId)}/${name}">${name}</a></p>`).join('');if(!wasComplete&&state.page===4)render();}
  }catch(e){$('#engine-status').textContent='작업 상태 조회 실패: '+e.message;}
}
async function connectEngine(){
  if(location.protocol==='file:'){$('#engine-status').textContent='로컬 서버를 실행해야 실제 해석을 사용할 수 있습니다. interface/launch.ps1 실행 → http://127.0.0.1:8765';return;}
  try{const r=await fetch('/api/health');const d=await r.json();localEngine=!!d.ok;$('#engine-status').textContent='로컬 Python 연결됨 · 실행 가능 범위 확인 후 시작하세요.';document.querySelector('.aside-note').innerHTML='해석 연결 상태<br><b>● 로컬 Python 연결됨</b><br>Motor-CAD 작업 실행 가능<br><br>실제 자동 설계 버튼에서<br>지원 범위를 확인하세요.';await pollJob();}catch{$('#engine-status').textContent='계산 서버 미연결 · interface/launch.ps1로 실행하세요.';}
}
const renderBeforeBackend=render;
render=function(){renderBeforeBackend();if(realJob?.result&&state.page===4)$('#subtitle').textContent='저장된 실제 해석 결과와 입력 조건·부족분을 확인합니다.';};
connectEngine();setInterval(pollJob,2500);render();
