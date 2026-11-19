const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1540,height:1050}}),errors=[],starts=[];
  async function refreshUI(){await page.locator('#tm-refresh').click();await page.waitForFunction(()=>!document.querySelector('#tm-refresh').disabled);}
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/verify',r=>r.abort());await page.route('**/api/motorcad/open',r=>r.abort());
  await page.route('**/api/task-queue/start',r=>{const data=r.request().postDataJSON();starts.push(data);if(data.allow_native)throw Error('Native execution must not be requested in this test');return r.continue();});
  await page.goto('http://127.0.0.1:8765/?job=20261022_165707');
  await page.waitForFunction(()=>typeof realJob!=='undefined'&&realJob?.result?.stage==='formula');
  await page.locator('#task-manager-open').click();await page.waitForSelector('#task-manager-modal[open]');
  await page.locator('#tm-import').click();
  await page.waitForFunction(()=>document.querySelector('#tm-detail').textContent.includes('88 /')||document.querySelector('#tm-detail').textContent.includes('0 / 88'));
  assert.equal(await page.locator('#tm-start').isDisabled(),true);
  assert.equal(await page.locator('#tm-native').count(),0);
  assert((await page.locator('#tm-detail').innerText()).includes('구체적인 모델'));
  await page.locator('.tm-create summary').click();await page.locator('#tm-create-mock').click();
  await page.waitForFunction(()=>document.querySelector('#tm-detail h3')?.textContent.includes('모의 실패'));
  const mockJob=await page.locator('.tm-detail-title small').innerText();
  await page.locator('#tm-start').click();
  for(let i=0;i<40;i++){
    await refreshUI();
    if(await page.locator('[data-tm-retry="solve"]').count())break;
    await page.waitForTimeout(100);
  }
  await page.locator('[data-tm-retry="solve"]').check();
  assert.equal(await page.locator('#tm-retry').isEnabled(),true);
  await page.locator('#tm-retry').click();
  for(let i=0;i<40;i++){
    await refreshUI();
    if((await page.locator('#tm-progress').getAttribute('value'))==='100')break;
    await page.waitForTimeout(100);
  }
  assert.equal(await page.locator('#tm-progress').getAttribute('value'),'100');
  await page.locator('[data-tm-tab="attempts"]').click();
  assert.equal(await page.locator('#tm-tab-content tr').count(),5);
  await page.locator('[data-tm-tab="tasks"]').click();
  await page.locator('[data-tm-result="compare"]').click();await page.waitForSelector('#tm-result-json');
  assert((await page.locator('#tm-result-json').innerText()).includes('mock_completed'));
  const url=await page.locator('#tm-tab-content a').first().getAttribute('href');
  const artifact=await page.request.get('http://127.0.0.1:8765'+url);assert.equal(artifact.status(),200);
  const bad=await page.request.get('http://127.0.0.1:8765'+url.replace('result.json','..%2Ftasks.sqlite'));assert.equal(bad.status(),404);
  const stopPlan=await page.request.post('http://127.0.0.1:8765/api/task-queue/create',{data:{title:'UI 중단·재개 모의 시험 '+Date.now(),tasks:[
    {id:'first',kind:'mock',payload:{value:'first',duration_s:1.5},estimate_s:1},
    {id:'last',kind:'mock',payload:{value:'last'},depends_on:['first'],estimate_s:1}
  ]}});
  const stopJob=(await stopPlan.json()).id;
  await refreshUI();await page.locator(`[data-tm-job="${stopJob}"]`).click();
  await page.locator('#tm-start').click();
  for(let i=0;i<30;i++){
    await refreshUI();if(await page.locator('#tm-stop').isEnabled())break;
    await page.waitForTimeout(50);
  }
  await page.locator('#tm-stop').click();
  for(let i=0;i<30;i++){
    await refreshUI();
    if((await page.locator('.tm-detail-title .tm-badge').innerText())==='중단됨')break;
    await page.waitForTimeout(100);
  }
  assert.equal(await page.locator('#tm-resume').isEnabled(),true);await page.locator('#tm-resume').click();
  for(let i=0;i<30;i++){
    await refreshUI();if((await page.locator('#tm-progress').getAttribute('value'))==='100')break;
    await page.waitForTimeout(100);
  }
  const resumed=await page.request.get('http://127.0.0.1:8765/api/task-queue?id='+stopJob);
  assert.deepEqual((await resumed.json()).tasks.map(t=>t.attempts),[1,1]);
  await page.locator('#tm-close').click();
  await page.locator('[data-page="4"]').click();
  await page.locator('#task-manager-open').click();
  await page.locator('#tm-create-verification').click();
  await page.waitForSelector('#tm-native');assert.equal(await page.locator('#tm-native').isChecked(),false);
  assert.equal(await page.locator('#tm-start').isDisabled(),true);
  await page.locator('#tm-native').check();assert.equal(await page.locator('#tm-start').isEnabled(),true);
  await page.locator('#tm-native').uncheck();
  assert(starts.every(s=>s.allow_native===false));assert.deepEqual(errors,[]);
  const out=path.resolve(__dirname,'../outputs/task_manager_ui_20261027');fs.mkdirSync(out,{recursive:true});
  await page.locator('#task-manager-modal').evaluate(el=>el.scrollTop=0);
  await page.locator('#task-manager-modal').screenshot({path:path.join(out,'desktop.png')});
  await page.setViewportSize({width:430,height:900});
  await page.locator('#task-manager-modal').evaluate(el=>el.scrollTop=0);
  assert.equal(await page.evaluate(()=>document.querySelector('#task-manager-modal').getBoundingClientRect().width<=innerWidth),true);
  await page.locator('#task-manager-modal').screenshot({path:path.join(out,'mobile.png')});
  let queueReads=0;page.on('request',r=>{if(r.url().includes('/api/task-queue')&&r.method()==='GET')queueReads++;});
  await page.locator('#tm-auto').check();await page.locator('#tm-close').click();const closedReads=queueReads;
  await page.waitForTimeout(5200);assert.equal(queueReads,closedReads);
  const report={passed:true,mockJob,stop_resume_job:stopJob,starts:starts.length,native_solves:0,page_errors:errors,closed_dialog_polling_stopped:true};
  fs.writeFileSync(path.join(out,'browser_check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
