const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const out=path.resolve(__dirname,'../outputs/breadloaf_input_check_20261104');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],native=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST'&&/\/api\/(breadloaf\/start|verify$|run$)/.test(r.url()))native.push(r.url());});
  await page.goto('http://127.0.0.1:8765/');await page.locator('#breadloaf-open').click();
  await page.locator('#bf-main-preview').click();await page.waitForFunction(()=>document.querySelector('#bf-main-preview-result').innerText.length>10);
  assert.equal(await page.locator('#bf-main-search').isDisabled(),true);
  await page.evaluate(()=>{state={...state,core:['50PN470'],grades:[48],suffix:['UH'],spm:{shape:'Breadloaf',magnetisation:'Radial'},
   temp:20,tmin:'',tmax:'',units:'mm',control:'FOC · Id = 0',modulation:'SVPWM',priority:'균형형',connection:'delta',eta:100,mechanical:0,margin:10,
   geometry:{},modes:{},ranges:{},rotorParameters:{surface_breadloaf:{pole_arc_ed:{mode:'fixed',value:61.5},magnet_reduction_mm:{mode:'fixed',value:.2}}},
   statorParameters:{slot_opening_mm:{mode:'range',min:1.1,max:1.3}},poleSlotCandidates:[{poles:4,slots:12}],switchingKHz:10,pwmCurrentRipplePct:15,
   ops:[{torque:.5,rpm:3200,vmin:9,vrated:12,vmax:16,eff:88}],fluxDensityMaxT:1.8};});
  await page.locator('#breadloaf-dialog details summary').first().click();
  await page.locator('#bf-iterations').fill('1');await page.locator('#bf-main-preview').click();await page.waitForFunction(()=>!document.querySelector('#bf-main-search').disabled);
  await page.screenshot({path:path.join(out,'input-preview.png'),fullPage:true});
  await page.locator('#bf-main-search').click();await page.waitForFunction(()=>document.querySelector('#bf-detail [data-bf-id]'),{},{timeout:30000});
  const job=await page.locator('#bf-jobs').inputValue();const data=await(await page.request.get('http://127.0.0.1:8765/api/breadloaf?id='+job)).json();
  assert.equal(data.state,'completed');assert.equal(data.request_contract.target_basis,'shaft');
  assert.ok(Math.abs(data.target_electromagnetic_torque_Nm-.55)<1e-12);assert.equal(data.request_contract.speed_rpm,3200);
  assert.equal(data.free_variable_count,1);assert.equal(data.full_grid_combinations,3);
  for(const row of data.rows){assert.equal(row.dimensions['Magnet_Arc_[ED]'],61.5);assert.equal(row.dimensions.MagnetReduction,.2);assert.ok(row.dimensions.Slot_Opening>=1.1&&row.dimensions.Slot_Opening<=1.3);}
  for(const row of data.rows){assert.ok(row.model_screens.available);assert.equal(row.model_screens.qualified,false);assert.equal(row.model_screens.efficiency_pct,null);assert.equal(row.model_screens.local_peak_iron_B_T,null);assert.equal(row.model_screens.checks.tooth_section_average_B.used_for_guidance,false);}
  await page.locator('#bf-detail h4').last().scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'electrical-screens.png'),fullPage:true});
  await page.locator('[data-bf-id]').first().check();await page.locator('#bf-prepare').click();await page.locator('#bf-start').waitFor();
  const batch=await page.locator('#bf-jobs').inputValue();const prepared=await(await page.request.get('http://127.0.0.1:8765/api/breadloaf?id='+batch)).json();
  assert.equal(prepared.request_contract.requested_shaft_torque_Nm,.55);assert.deepEqual(prepared.request_contract.voltages_V,[9,12,16]);
  assert.equal(prepared.rows.length,1);assert.equal(prepared.state,'prepared');
  assert.deepEqual(errors,[]);assert.deepEqual(native,[]);
  fs.writeFileSync(path.join(out,'browser_check.json'),JSON.stringify({passed:true,job,batch,errors,native_posts:0,
   checks:['unsupported main inputs blocked','torque margin propagated','shaft basis preserved','RPM and voltages retained','selected candidate only','FEA not launched']},null,2));
  console.log('PASS: main-input contract, margin, saved conditions and no native launch');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
