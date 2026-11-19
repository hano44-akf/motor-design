/* Fixed physical dimension resolution; angular and electrical values are separate. */
const conditionsBeforeDimensionGrid=conditions;
conditions=function(){return conditionsBeforeDimensionGrid()+panel('설계 치수 해상도',
  '<p>설계 치수 입력과 탐색은 <b>0.1 mm 간격</b>으로 적용합니다. 모든 조합을 스윕하는 방식은 아닙니다. 턴 수는 정수, 각도·전류·성능값은 별도 기준입니다.</p><p class="muted">도체 외경은 절연 여유를 보존하도록 0.1 mm 단위로 올림합니다. 권선 배치에서 계산되는 단부 길이 등 파생값은 손실 계산을 위해 원래 정밀도를 유지합니다.</p>');};
const studyBeforeDimensionGrid=toStudyRequest;
toStudyRequest=function(){
  const request=studyBeforeDimensionGrid();
  request.bounds.forEach(([lo,hi],i)=>{
    const factor=i===2?1:10;
    if(Math.ceil(lo*factor-1e-8)>Math.floor(hi*factor+1e-8))throw Error('지정 범위에 0.1 mm 간격의 치수가 없습니다. 고정 치수는 0.1 mm 단위로 입력하세요.');
  });
  return {...request,dimension_resolution_mm:0.1};
};
render();
