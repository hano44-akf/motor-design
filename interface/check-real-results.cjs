const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});try{
 const p=await b.newPage({viewport:{width:1440,height:1000}});const errors=[];p.on('pageerror',e=>errors.push(e.message));
 await p.goto('http://127.0.0.1:8765/?job=20261022_085158');await p.waitForFunction(()=>!!realJob?.result);await p.locator('[data-page="4"]').click();
 assert.match(await p.locator('#content').innerText(),/실제 PyMotorCAD 해석 결과/);
 assert.equal(await p.evaluate(()=>realJob.result.results.filter(c=>c.target_met).length),3);
 await p.screenshot({path:__dirname+'/actual-results.png',fullPage:true});
 await p.locator('#engine-open').click();const dl=p.waitForEvent('download');await p.getByRole('link',{name:'motorcad.csv',exact:true}).click();
 const f=await dl;const csv=fs.readFileSync(await f.path(),'utf8');assert.equal(csv.charCodeAt(0),0xfeff);assert.match(csv,/0.50269/);
 await p.locator('#engine-close').click();await p.setViewportSize({width:390,height:844});
 assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
 console.log('PASS: real result display, 3 target-met models, actual CSV download, mobile layout, no JS errors');
}finally{await b.close();}})();
