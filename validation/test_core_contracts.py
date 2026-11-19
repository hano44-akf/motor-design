import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from request_schema import validate_input,domain_snapshot
from model_capabilities import check_model_support,validate_for_model
from result_policy import requirement,summarize_requirements,shortfall_summary,candidate_rank

ROOT=Path(__file__).resolve().parent


class CoreContractTests(unittest.TestCase):
    def request(self):
        return json.loads((ROOT/'jobs/20261022_162610/request.json').read_text(encoding='utf-8'))

    def test_valid_but_unsupported_does_not_mean_bad_input(self):
        for key,value in [('connection','star'),('strands',2),('core','unregistered material'),('control','six_step')]:
            r=self.request();r[key]=value;validate_input(r)
            self.assertTrue(check_model_support(r)['input_valid'])
            self.assertFalse(check_model_support(r)['supported'])
            with self.assertRaises(ValueError):validate_for_model(r,'formula')
        r=self.request();r['pole_slot_candidates']=[{'poles':10,'slots':12}]
        validate_input(r);self.assertFalse(check_model_support(r)['supported'])

    def test_invalid_numbers_and_empty_grid_rejected(self):
        for value in (True,float('nan'),float('inf'),-1,'3500'):
            r=self.request();r['operating_point']['speed_rpm']=value
            with self.assertRaises(ValueError):validate_input(r)
        r=self.request();r['bounds'][0]=[55.01,55.09]
        with self.assertRaises(ValueError):validate_input(r)

    def test_saved_design_verification_can_select_only_minimum_voltage(self):
        r=self.request();r['operating_point']['voltages_V']=[9]
        with self.assertRaises(ValueError):validate_input(r)
        r['formula_source_job']='20261022_165707'
        validate_input(r)
        r=self.request();r['search_rounds']=1.5
        with self.assertRaises(ValueError):validate_input(r)

    def test_si_snapshot_is_versioned_and_input_is_immutable(self):
        r=self.request();before=copy.deepcopy(r);s=domain_snapshot(r)
        self.assertEqual(r,before)
        self.assertEqual(s['schema'],'motor-study-domain-v1')
        self.assertAlmostEqual(s['search_variables'][0]['min'],.055)
        self.assertEqual(s['search_variables'][0]['step'],.0001)
        self.assertEqual(s['search_variables'][2]['step'],1)
        self.assertAlmostEqual(s['temperatures_K'][0],293.15)
        self.assertEqual(s['limits']['flux_density_max_T'],1.8)
        r['operating_point']['efficiency_min_pct']=None
        self.assertIsNone(domain_snapshot(r)['operating_points'][0]['efficiency_min_pct'])

    def test_unknown_inactive_violated_and_zero_limit_are_distinct(self):
        items={'ripple':requirement(None,20,'max'),'efficiency':requirement(90,None),
               'torque':requirement(.49,.5),'zero':requirement(0,0,'max')}
        summary=summarize_requirements(items)
        self.assertEqual(summary['unverified'],['ripple'])
        self.assertEqual(summary['violated'],['torque'])
        self.assertEqual(items['efficiency']['state'],'not_applicable')
        self.assertEqual(items['zero']['state'],'passed')
        self.assertFalse(summary['passed'])
        missing=summarize_requirements({'ripple':items['ripple']})
        self.assertEqual(missing['status'],'verification_incomplete')
        review=shortfall_summary({'torque':.01,'ripple':None},{'torque':.5,'ripple':20})
        self.assertAlmostEqual(review['known_normalized_shortfall'],.02)
        self.assertFalse(review['complete'])

    def test_formula_executes_when_native_sdk_and_legacy_runner_are_unavailable(self):
        # Fresh interpreter proves that imports already cached by other tests
        # cannot conceal a dependency on the native SDK or monolithic runner.
        code='''
import importlib.abc,json,sys
from pathlib import Path
class BlockNative(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in ('ansys','low_voltage','design_job'):
   raise AssertionError('Native dependency imported: '+fullname)
sys.meta_path.insert(0,BlockNative())
from formula_job import run_formula
r=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
r['bounds']=[[85,85],[20,20],[6,6],[1.8,1.8]]
r['airgap_bounds_mm']=[.5,.5]
out=run_formula(r,Path(sys.argv[2]))
assert out['search_statistics']['motorcad_solves']==0
assert Path(sys.argv[2],'domain_request.json').is_file()
assert Path(sys.argv[2],'model_support.json').is_file()
'''
        with tempfile.TemporaryDirectory() as tmp:
            completed=subprocess.run([sys.executable,'-c',code,str(ROOT/'jobs/20261022_162610/request.json'),tmp],
                cwd=ROOT,capture_output=True,text=True,timeout=30)
            self.assertEqual(completed.returncode,0,completed.stderr)

    def test_provisional_rank_keeps_unknown_separate_from_numeric_deficit(self):
        unknown={'requirement_summary':summarize_requirements({'ripple':requirement(None,20,'max')})}
        violated={'requirement_summary':summarize_requirements({'ripple':requirement(21,20,'max')})}
        unknown_deficit=shortfall_summary({'ripple':None},{'ripple':20})
        violated_deficit=shortfall_summary({'ripple':1},{'ripple':20})
        rank=candidate_rank([unknown],[unknown_deficit])
        self.assertEqual(rank,(False,0,1))
        self.assertLess(rank,candidate_rank([violated],[violated_deficit]))
        self.assertFalse(unknown['requirement_summary']['passed'])


if __name__=='__main__':unittest.main()
