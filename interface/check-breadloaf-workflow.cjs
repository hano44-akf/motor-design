const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const out=path.resolve(__dirname,'../outputs/breadloaf_gui_check_20261104');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[],native=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.method()==='POST'&&/\/api\/(breadloaf\/start|verify$|run$|task-queue\/start)/.test(r.url()))native.push(r.url());});
  await page.goto('http://127.0.0.1:8765/');await page.locator('#breadloaf-open').waitFor();
  await page.locator('[data-page="4"]').click();
  await page.locator('#breadloaf-results table').first().waitFor();
  assert.match(await page.locator('#breadloaf-results').innerText(),/13.683/);
  await page.locator('#breadloaf-open').click();await page.locator('#bf-detail table').first().waitFor();
  assert.match(await page.locator('#bf-detail').innerText(),/0.49988/);
  assert.match(await page.locator('#bf-detail').innerText(),/0.48245/);
  await page.screenshot({path:path.join(out,'desktop.png'),fullPage:true});
  await page.locator('#bf-jobs').selectOption('pilot-search');
  await page.locator('[data-bf-id]').first().waitFor();
  await page.locator('[data-bf-id]').first().check();
  await page.locator('#bf-prepare').click();await page.locator('#bf-start').waitFor();
  assert.match(await page.locator('#bf-start').innerText(),/\(1/);
  const selected=await page.locator('#bf-jobs').inputValue();assert.match(selected,/^bf_/);
  const data=await (await page.request.get('http://127.0.0.1:8765/api/breadloaf?id='+selected)).json();
  assert.equal(data.rows.length,1);assert.equal(data.state,'prepared');
  assert.equal((await page.request.get('http://127.0.0.1:8765/api/breadloaf?id=..%2F..')).status(),400);
  await page.locator('#breadloaf-dialog details summary').first().click();
  await page.locator('#bf-iterations').fill('1');
  await page.locator('#bf-search-form button').click();
  await page.waitForFunction(()=>document.querySelector('#bf-jobs').value.startsWith('bf_')&&document.querySelector('#bf-jobs').value!==document.querySelector('#bf-start')?.dataset?.id);
  await page.waitForFunction(()=>document.querySelector('#bf-detail [data-bf-id]'),{},{timeout:30000});
  const searchId=await page.locator('#bf-jobs').inputValue();
  const search=await (await page.request.get('http://127.0.0.1:8765/api/breadloaf?id='+searchId)).json();
  assert.equal(search.state,'completed');assert.ok(search.statistics.unique_candidates>0);
  await page.locator('#bf-jobs').selectOption(selected);await page.locator('#bf-start').waitFor();
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  assert.equal(await page.locator('#breadloaf-dialog').evaluate(el=>el.scrollWidth>el.clientWidth+1),false);
  await page.screenshot({path:path.join(out,'mobile.png'),fullPage:true});
  await page.locator('#bf-close').click();
  await page.locator('#task-manager-open').click();await page.locator('#tm-breadloaf').click();
  await page.locator('#breadloaf-dialog').waitFor({state:'visible'});
  assert.deepEqual(native,[]);assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'browser_check.json'),JSON.stringify({passed:true,errors,native_posts:native.length,
   prepared_batch:selected,search_job:searchId,checks:['result metrics','electromagnetic vs shaft torque','selected candidate only','prepare does not execute FEA','CPU search from GUI','task manager entry','mobile overflow','invalid id']},null,2));
  console.log('PASS: Breadloaf GUI selection, task entry, mobile and no native launch');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
