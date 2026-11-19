const {chromium}=require('C:/Users/jo061/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1100}}),errors=[],previews=[];
  page.on('pageerror',e=>errors.push(e.message));
  for(const endpoint of ['verify','motorcad/open','optimize'])await page.route('**/api/'+endpoint,r=>r.abort());
  await page.goto('http://127.0.0.1:8765/');
  await page.waitForFunction(()=>typeof rotorCatalog!=='undefined'&&!!rotorCatalog?.detailed_spm_geometry);
  assert.equal(await page.evaluate(()=>rotorCatalog.policy.thermal_analysis_enabled),false);
  assert.equal(await page.evaluate(()=>rotorCatalog.policy.structural_analysis_enabled),false);
  assert.equal(await page.evaluate(()=>rotorCatalog.rotors.some(r=>r.constraint_ids.includes('mechanical_integrity'))),false);
  await page.locator('#engine-open').click();await page.locator('#engine-example').click();await page.locator('#engine-close').click();
  await page.locator('[data-page="1"]').click();
  await page.locator('[data-stator-mode="slot_depth_mm"]').selectOption('range');
  await page.locator('[data-stator-param="slot_depth_mm"][data-bound="min"]').fill('9');
  await page.locator('[data-stator-param="slot_depth_mm"][data-bound="max"]').fill('11');
  async function preview(){
   const [response]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/geometry/spm/preview')),page.locator('#spm-geometry-preview').click()]);
   assert.equal(response.status(),200);const result=await response.json();previews.push(result);assert.equal(result.motorcad_solves,0);return result;
  }
  let r=await preview();assert.equal(r.designs[0].native_dimension_candidates.Slot_Depth,10);
  assert.deepEqual(await page.evaluate(()=>toStudyRequest().geometry_parameters.slot_depth_mm),{mode:'range',min:9,max:11});
  await page.locator('[data-spm="shape"]').selectOption('Breadloaf');
  await page.locator('[data-rotor-mode="magnet_reduction_mm"]').selectOption('range');
  await page.locator('[data-rotor-param="magnet_reduction_mm"][data-bound="min"]').fill('.2');
  await page.locator('[data-rotor-param="magnet_reduction_mm"][data-bound="max"]').fill('.8');
  r=await preview();assert.equal(r.designs[0].breadloaf_reduction_mm,.5);
  assert.equal(r.designs[0].derived_geometry.magnet_edge_thickness_mm,null);assert.equal(r.optimization_connected,false);
  const out=path.resolve(__dirname,'../outputs/spm_geometry_scope_20261027');fs.mkdirSync(out,{recursive:true});
  await page.locator('#spm-geometry-result').locator('xpath=ancestor::section').screenshot({path:path.join(out,'geometry_panel.png')});
  await page.locator('[data-rotor-mode="magnet_reduction_mm"]').selectOption('fixed');
  await page.locator('[data-rotor-param="magnet_reduction_mm"][data-bound="value"]').fill('3');
  r=await preview();assert.equal(r.designs[0].envelope_checks_passed,false);
  assert(r.designs[0].violations.includes('reduction_below_center_thickness'));
  const imported=await page.request.post('http://127.0.0.1:8765/api/task-queue/import-checklist',{data:{}});
  const queue=await imported.json();assert.equal(queue.total_tasks,88);
  assert.equal(queue.tasks.filter(t=>t.id.endsWith('_demagnetization')).length,11);
  assert.equal(queue.tasks.filter(t=>t.id.endsWith('_safety')).length,0);
  assert.deepEqual(errors,[]);
  const report={passed:true,page_errors:errors,preview_calls:previews.length,thermal_excluded:true,structural_excluded:true,demagnetization_tasks:11,motorcad_solves:0};
  fs.writeFileSync(path.join(out,'browser_check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
