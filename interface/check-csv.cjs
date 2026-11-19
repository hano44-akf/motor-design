const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('file:///C:/work/codex/motor%20design/interface/index.html');
  await page.locator('#csv-export').click();
  const event=page.waitForEvent('download');await page.locator('[data-csv="inputs"]').click();
  const download=await event;const csv=fs.readFileSync(await download.path(),'utf8');
  assert.equal(csv.charCodeAt(0),0xfeff);assert.match(csv,/현재 화면/);
  assert.ok(await page.locator('[data-csv="imported"]').isDisabled());
  await page.locator('#csv-import').setInputFiles('validation/csv_exports/pilot_arc120_bundle.json');
  await page.waitForFunction(()=>document.querySelector('#csv-import-status').textContent.includes('준비 완료'));
  const rows=await page.evaluate(()=>exportRows('imported'));
  assert.ok(rows.some(r=>r[2]==='values.Shaft Torque'&&r[3]===0.59062));
  assert.ok(rows.some(r=>r[2]==='values.Speed limit for zero q axis current'&&r[3]==='inf'));
  const example=await page.evaluate(()=>exportRows('results'));
  assert.ok(example.some(r=>r[5].includes('가상 예제')));
  assert.equal(await page.evaluate(()=>csvText([['a,"b\nc',null,'=1+1',-2]])), '\ufeff"a,""b\nc","","\'=1+1","-2"\r\n');
  assert.deepEqual(errors,[]);console.log('PASS: CSV download, BOM, saved FEA import, nonfinite state, example labels, quoting, blanks, formula escaping');
 }finally{await browser.close();}
})();
