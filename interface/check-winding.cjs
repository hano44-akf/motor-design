const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1100}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/verify',r=>r.abort());
  await page.route('**/api/motorcad/open',r=>r.abort());
  await page.goto('http://127.0.0.1:8765/');
  await page.waitForFunction(()=>typeof rotorCatalog!=='undefined'&&rotorCatalog?.rotors.length===16);
  await page.locator('#engine-open').click();await page.locator('#engine-example').click();await page.locator('#engine-close').click();
  await page.evaluate(()=>{state.poleSlotCandidates=[{poles:4,slots:12},{poles:8,slots:12},{poles:10,slots:12}];state.ops[0].rpm=3500;render();});
  await page.locator('[data-page="1"]').click();
  await page.waitForSelector('#pole-slot-winding-review');
  const table=await page.locator('#pole-slot-winding-review').innerText();
  assert(table.includes('0.8660'));assert(table.includes('0.9330'));assert(table.includes('291.67'));
  assert.equal(await page.locator('#pole-slot-winding-review tr').count(),4);
  const [saved]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/topology/plan')),page.locator('#save-topology-plan').click()]);
  assert.equal(saved.status(),200);const plan=await saved.json();assert.equal(plan.pending_task_count,24);assert.equal(plan.motorcad_solves,0);
  await page.locator('#pole-slot-winding-review').screenshot({path:__dirname+'/pole-slot-winding-review.png'});
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,pairs:3,native_solves:0,table}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
