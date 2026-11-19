const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const out=path.resolve(__dirname,'../outputs/result_review_ui_20261027');fs.mkdirSync(out,{recursive:true});
 const b=await chromium.launch({channel:'msedge',headless:true});
 try{
  const p=await b.newPage({viewport:{width:1440,height:1000}});const errors=[],mutations=[];
  p.on('pageerror',e=>errors.push(e.message));
  p.on('request',r=>{if(r.method()==='POST'&&/\/api\/(optimize|verify|run|task-queue\/start)/.test(r.url()))mutations.push(r.url());});
  await p.goto('http://127.0.0.1:8765/?job=20261027_095545_502342500');
  await p.waitForFunction(()=>!!realJob?.result);await p.locator('[data-page="4"]').click();
  const review=p.locator('#result-requirement-review');await review.waitFor();
  await p.waitForFunction(()=>document.querySelector('#result-requirement-review')?.dataset.job==='20261027_095545_502342500');
  assert.match(await review.innerText(),/진단용 비교 대상/);
  assert.match(await review.innerText(),/미검증/);assert.match(await review.innerText(),/불만족/);
  assert.match(await review.innerText(),/목표 제외/);
  const data=await (await p.request.get('http://127.0.0.1:8765/api/result-review?id=20261027_095545_502342500')).json();
  assert.equal(data.motorcad_solves,0);assert.equal(data.best_available,null);
  assert.equal((await p.request.get('http://127.0.0.1:8765/api/result-review?id=..%2F..')).status(),400);
  assert.ok(data.candidates[0].runs[0].model_path.endsWith('.mot'));
  await p.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
  await p.setViewportSize({width:390,height:844});
  assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await p.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
  await p.goto('http://127.0.0.1:8765/?job=20261022_165707');await p.waitForFunction(()=>!!realJob?.result);
  await p.locator('[data-page="4"]').click();
  await p.waitForFunction(()=>document.querySelector('#result-requirement-review')?.dataset.job==='20261022_165707');
  assert.match(await p.locator('#result-requirement-review').innerText(),/수식 예측 단계/);
  assert.equal(await p.locator('#result-requirement-review .rr-requirements_passed').count(),0);
  assert.deepEqual(errors,[]);assert.deepEqual(mutations,[]);
  fs.writeFileSync(path.join(out,'browser_check.json'),JSON.stringify({passed:true,native_calls:mutations.length,errors,checks:['known and unknown requirements','diagnostic fallback','source model path','formula-only unverified','mobile overflow','invalid job rejected']},null,2));
  console.log('PASS: saved result review, formula-only unverified, mobile layout, no native execution');
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
