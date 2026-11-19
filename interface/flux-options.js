/* One common maximum for iron regions, stored in tesla. */
if(state.fluxDensityMaxT===undefined)state.fluxDensityMaxT='';
function effectiveFluxDensity(){
  const value=state.fluxDensityMaxT;
  if(value===''||value===null||value===undefined)return 1.8;
  if(!Number.isFinite(Number(value))||Number(value)<=0)throw Error('최대 철심 자속밀도는 양수로 입력하세요. 공란은 1.8 T입니다.');
  return Number(value);
}
const conditionsBeforeFlux=conditions;
conditions=function(){return conditionsBeforeFlux()+panel('철심 자속밀도 제한',
  field('최대 철심 자속밀도','fluxDensityMaxT','T',state.fluxDensityMaxT,'공란 = 1.8 T')+
  '<p class="muted">고정자 치·치끝·고정자 요크·회전자 요크에 공통 적용합니다. Motor-CAD의 각 영역 최대값 중 하나라도 상한을 초과하면 목표 미달입니다. 값이 없으면 미검증으로 표시합니다.</p>');};
const studyBeforeFlux=toStudyRequest;
toStudyRequest=function(){const limit=effectiveFluxDensity();return {...studyBeforeFlux(),flux_density_max_T:limit};};
const reviewBeforeFlux=review;
review=function(){reviewBeforeFlux();try{$('#reviewbody').insertAdjacentHTML('beforeend',`<p>최대 철심 자속밀도: ${esc(effectiveFluxDensity())} T 이하 · 공란 기본 1.8 T</p>`);}catch(e){$('#reviewbody').insertAdjacentHTML('beforeend',`<p class="error">${esc(e.message)}</p>`);}};
$('#review').onclick=review;
const resultsBeforeFlux=results;
results=function(){
  let html=resultsBeforeFlux();
  if(!realJob?.result)return html;
  const r=realJob.result,hasLimit=r.effective_flux_density_max_T!==undefined;
  const fields=['Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)','Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)'];
  const rows=r.results.map(c=>c.runs.map(x=>{
    const check=x.assessment.flux_density;
    const status=!check?'기존 작업 · 상한 미적용':check.passed===false?'목표 미달':check.passed===true?'상한 이내':'미검증';
    return `<tr><td>${esc(c.id)} / ${esc(x.input_options.temperature_C)}°C / ${esc(x.design.voltage_V)} V</td>${fields.map(k=>`<td>${Number.isFinite(x.values[k])?esc(x.values[k].toFixed(3)):'미검증'}</td>`).join('')}<td>${status}</td></tr>`;
  }).join('')).join('');
  html+=panel('철심 자속밀도 검증',`<p>${hasLimit?'이 작업의 최대값: '+esc(r.effective_flux_density_max_T)+' T':'기존 저장 작업: 자속밀도 상한 미적용 · 새 작업부터 공란 기본 1.8 T 적용'}</p><div class="scroll"><table><tr><th>모델 / 온도 / DC</th><th>치 [T]</th><th>치끝 [T]</th><th>고정자 요크 [T]</th><th>회전자 요크 [T]</th><th>판정</th></tr>${rows}</table></div><p class="muted">Motor-CAD의 영역별 경로 최대값 기준입니다. 전체 메시의 국부 최대값이나 포화율(%)과는 다릅니다. 저비용 수식 모델은 B를 직접 예측하지 않으므로 Motor-CAD 검증 단계에서 판정하며, 초과 모델도 부족분과 함께 반환합니다.</p>`);
  return html;
};
document.addEventListener('click',e=>{if(e.target.closest('#engine-example')){state.fluxDensityMaxT='';persist();render();}});
render();
