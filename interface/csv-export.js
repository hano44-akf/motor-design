/* CSV transport only. Imported runs never become validated current UI models. */
let importedExportData=null;
function csvText(rows){
  const cell=v=>{let s=v===null||v===undefined?'':String(v);if(typeof v==='string'&&/^[\s]*[=+@-]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
  return '\ufeff'+rows.map(row=>row.map(cell).join(',')).join('\r\n')+'\r\n';
}
function csvFlatten(value,path='',out=[]){
  if(value!==null&&typeof value==='object')Object.entries(value).forEach(([k,v])=>csvFlatten(v,path?path+'.'+k:k,out));
  else out.push([path,value]);
  return out;
}
function exportRows(kind){
  const rows=[['구분','모델/출처','항목','값','단위/기준','상태']];
  if(kind==='inputs'){
    csvFlatten(state).forEach(([k,v])=>rows.push(['입력','현재 화면',k,v,'저장값 기준; geometry/ranges 길이='+state.units+'; 운전점 V,N·m,rpm,A,%','입력 스냅샷']));
  }else if(kind==='results'){
    for(const m of models)for(const key of ['temp','tmin','tmax']){
      const t=state[key]===''||state[key]===undefined?null:Number(state[key]),a=analytical(m,t);
      for(const [label,k,unit,note] of resultRows())rows.push(['수식 예제',m.id,`${key}=${t===null?'미입력':t+'°C'} / ${label}`,a[k]??'',unit?unitChoices[unit].base:'항목명 기준',`가상 예제 · 현재 입력 최적화 결과 아님 · ${note}`]);
      csvFlatten(m).forEach(([k,v])=>rows.push(['예제 형상',m.id,k,v,'원본 예제 단위: 길이 mm','가상 예제']));
    }
  }else if(kind==='imported'){
    if(!importedExportData)throw Error('저장 결과 JSON을 먼저 불러오세요.');
    csvFlatten(importedExportData.data).forEach(([k,v])=>rows.push(['저장 결과',importedExportData.source,k,v,'원본 필드명·메타데이터 기준','불러온 기록 · 현재 입력과 연결되지 않음']));
  }
  return rows;
}
function downloadCsv(kind){
  const url=URL.createObjectURL(new Blob([csvText(exportRows(kind))],{type:'text/csv;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=`motor_${kind}_${new Date().toISOString().replace(/[:.]/g,'-')}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const csvDialog=document.createElement('dialog');csvDialog.id='csv-dialog';
csvDialog.innerHTML='<h2>CSV 내보내기</h2><p>Excel에서 한글을 읽을 수 있는 UTF-8 BOM 형식입니다. 공란은 공란으로 보존합니다.</p><p><button data-csv="inputs">현재 입력값 CSV</button> <button data-csv="results">화면 예제 결과 CSV</button></p><p>실제 최적화·PyMotorCAD 결과는 저장 결과 JSON 또는 export_csv.py의 bundle.json을 불러오세요. 현재 화면의 예제와 별도로 내보냅니다.</p><input id="csv-import" type="file" accept=".json"><p id="csv-import-status" aria-live="polite">불러온 결과 없음</p><button data-csv="imported" disabled>불러온 해석·최적화 결과 CSV</button> <button id="csv-close">닫기</button>';
document.body.append(csvDialog);
const csvButton=document.createElement('button');csvButton.id='csv-export';csvButton.textContent='CSV 내보내기';$('.toolbar').append(csvButton);
csvButton.onclick=()=>csvDialog.showModal();
$('#csv-close').onclick=()=>csvDialog.close();
csvDialog.addEventListener('click',e=>{const b=e.target.closest('[data-csv]');if(b)downloadCsv(b.dataset.csv);});
$('#csv-import').onchange=async e=>{
  importedExportData=null;csvDialog.querySelector('[data-csv="imported"]').disabled=true;
  try{const f=e.target.files[0];if(!f)return;const obj=JSON.parse((await f.text()).replace(/^\ufeff/,''));const data=obj.schema==='motor-csv-export-v1'?obj.data:obj;
    if(!data||typeof data!=='object'||Array.isArray(data)||!['values','predictions','results','runs'].some(k=>k in data))throw Error('지원되는 해석/최적화 결과가 아닙니다.');
    importedExportData={source:f.name,data};$('#csv-import-status').textContent=f.name+' · 저장 결과 준비 완료';csvDialog.querySelector('[data-csv="imported"]').disabled=false;
  }catch(err){$('#csv-import-status').textContent='불러오기 실패: '+err.message+' 비표준 Infinity/NaN이 있는 원본은 export_csv.py로 변환하세요.';}
  e.target.value='';
};
