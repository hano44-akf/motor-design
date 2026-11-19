import copy
import json
from pathlib import Path
import unittest
from design_job import validate,assess_run
from motorcad_adapter import apply_checked

ROOT=Path(__file__).resolve().parent

class JobTests(unittest.TestCase):
    def setUp(self):
        self.request=json.loads((ROOT/'requests/low_voltage.json').read_text(encoding='utf-8'))

    def test_unsupported_inputs_do_not_silently_fall_back(self):
        for key,value in [('connection','star'),('control','six_step'),('strands',2),('core','unknown')]:
            request=copy.deepcopy(self.request);request[key]=value
            with self.assertRaises(ValueError):validate(request)
        request=copy.deepcopy(self.request);request['bounds'][0]=[55,200]
        with self.assertRaises(ValueError):validate(request)

    def test_mapping_mismatch_fails_before_solve(self):
        class IgnoredInputs:
            def set_variable(self,key,value):pass
            def get_variable(self,key):return 0
        with self.assertRaises(RuntimeError):apply_checked(IgnoredInputs(),{'shape':'Breadloaf','magnetisation':'Radial'})

    def test_peak_voltage_rejects_existing_infeasible_run(self):
        run=json.loads((ROOT/'optimization_12V_50PN470/pilot_arc120.json').read_text(encoding='utf-8'))
        assessment=assess_run(run,self.request)
        self.assertFalse(assessment['checks']['peak_voltage'])
        self.assertFalse(assessment['physical_screens_pass'])
        self.assertFalse(assessment['target_met'])

if __name__=='__main__':unittest.main()
