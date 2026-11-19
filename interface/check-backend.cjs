const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8765/?job=20261022_085158');await page.locator('#engine-open').click();
 await page.locator('#engine-example').click();
 let request=await page.evaluate(()=>toStudyRequest());assert.equal(request.operating_point.torque_Nm,.5);assert.deepEqual(request.operating_point.voltages_V,[9,12,16]);assert.equal(request.spm.magnetisation,'Radial');
 await page.locator('#engine-close').click();await page.locator('[data-page="1"]').click();
 await page.locator('[data-mode="od"]').selectOption('range');await page.locator('[data-geom="od"][data-bound="min"]').fill('70');await page.locator('[data-geom="od"][data-bound="max"]').fill('90');
 await page.locator('[data-open-units]').first().click();await page.locator('[data-unit-option="length"]').selectOption('m');await page.locator('#apply-units').click();
 request=await page.evaluate(()=>toStudyRequest());assert.deepEqual(request.bounds[0],[70,90]);
 await page.locator('[data-mode="gap"]').selectOption('fixed');await page.locator('[data-geom="gap"][data-bound="fixed"]').fill('0.001');
 assert.match(await page.evaluate(()=>{try{toStudyRequest();return '';}catch(e){return e.message;}}),/자동 비례/);
 assert.deepEqual(errors,[]);console.log('PASS: local engine UI, request mapping, SI/display conversion, unsupported fixed geometry rejection');
}finally{await browser.close();}})();
