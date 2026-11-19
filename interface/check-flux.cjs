const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});try{
 const p=await b.newPage({viewport:{width:1440,height:1000}}),errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto('http://127.0.0.1:8765/?job=20261022_091847');await p.waitForFunction(()=>!!realJob?.result);
 await p.locator('#engine-open').click();await p.locator('#engine-example').click();await p.locator('#engine-close').click();
 assert.equal(await p.evaluate(()=>toStudyRequest().flux_density_max_T),1.8);
 await p.locator('[data-page="2"]').click();
 const field=p.locator('[data-key="fluxDensityMaxT"]');await field.fill('1.6');
 assert.equal(await p.evaluate(()=>toStudyRequest().flux_density_max_T),1.6);
 await p.reload();await p.waitForFunction(()=>!!realJob?.result);
 assert.equal(await p.evaluate(()=>state.fluxDensityMaxT),1.6);
 await p.locator('[data-page="2"]').click();await field.fill('0');
 assert.match(await p.evaluate(()=>{try{toStudyRequest();return '';}catch(e){return e.message;}}),/양수/);
 await field.fill('');assert.equal(await p.evaluate(()=>toStudyRequest().flux_density_max_T),1.8);
 await p.locator('[data-page="4"]').click();assert.match(await p.locator('#content').innerText(),/상한 미적용/);
 assert.match(await p.locator('#content').innerText(),/2.076/);assert.deepEqual(errors,[]);
 console.log('PASS: flux UI default, override, persistence, validation and historical result scope');
}finally{await b.close();}})();
