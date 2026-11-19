const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const out=path.resolve(__dirname,'../outputs/breadloaf_model_check_20261105');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const p=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],native=[];
  p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(r.method()==='POST'&&/\/api\/(breadloaf\/start|verify$|run$)/.test(r.url()))native.push(r.url());});
  await p.goto('http://127.0.0.1:8765/');await p.locator('#breadloaf-open').click();
  await p.evaluate(()=>{state={...state,core:['50PN470'],grades:[48],suffix:['UH'],spm:{shape:'Breadloaf',magnetisation:'Radial'},
   temp:20,tmin:'',tmax:'',units:'mm',control:'FOC · Id = 0',modulation:'SVPWM',priority:'균형형',connection:'delta',eta:100,mechanical:0,margin:0,
   geometry:{},modes:{},ranges:{},rotorParameters:{surface_breadloaf:{pole_arc_ed:{mode:'fixed',value:67},magnet_reduction_mm:{mode:'fixed',value:.2}}},
   statorParameters:{slot_opening_mm:{mode:'fixed',value:1.6}},poleSlotCandidates:[{poles:4,slots:12}],switchingKHz:10,pwmCurrentRipplePct:15,
   ops:[{torque:.7,rpm:3500,vmin:9,vrated:12,vmax:16,eff:88}],fluxDensityMaxT:1.8};});
  await p.locator('#bf-main-preview').click();await p.waitForFunction(()=>!document.querySelector('#bf-main-search').disabled);
  await p.locator('#bf-main-search').click();await p.waitForFunction(()=>document.querySelector('#bf-detail [data-bf-id]'),{},{timeout:30000});
  const job=await p.locator('#bf-jobs').inputValue();const data=await(await p.request.get('http://127.0.0.1:8765/api/breadloaf?id='+job)).json();
  assert.equal(data.rows.length,1);assert.equal(data.selection_status,'best_effort_current_limited');
  assert.equal(data.rows[0].shaft_control_status,'model_target_unmet');
  assert.ok(data.rows[0].predicted_shaft_torque_Nm<.7);
  assert.ok(await p.locator('#bf-detail').innerText().then(t=>t.includes('국소 예측')));
  const model=data.rows[0].model_screens.local_calibrated_estimate;
  assert.ok(model.available);assert.ok(model.inside_development_hull);assert.equal(model.qualified,false);
  assert.ok(model.efficiency_pct>0&&model.efficiency_pct<100);assert.ok(model.local_peak_B_estimate_T>0);
  assert.equal(data.rows[0].model_screens.checks.tooth_section_average_B.used_for_guidance,false);
  await p.locator('#bf-detail h4').last().scrollIntoViewIfNeeded();await p.screenshot({path:path.join(out,'local-model.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(native,[]);
  fs.writeFileSync(path.join(out,'browser_check.json'),JSON.stringify({passed:true,job,errors,native_posts:0,
   local_efficiency_pct:model.efficiency_pct,local_peak_B_T:model.local_peak_B_estimate_T,
   checks:['local estimate in domain','not FEA qualified','raw B not used','torque shortfall retained','no native launch']},null,2));
  console.log('PASS: local loss/B model display, unverified labels and no native launch');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
