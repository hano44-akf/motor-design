import copy
import json
import math
from pathlib import Path
import unittest
from flux_limits import IRON_FIELDS, flux_density_limit, flux_density_review
from design_job import assess_run, validate


class FluxTests(unittest.TestCase):
    def test_default_override_invalid(self):
        for value in (None, ''):self.assertEqual(flux_density_limit(value), 1.8)
        self.assertEqual(flux_density_limit(1.6), 1.6)
        for value in (True, False, 0, -1, math.nan, math.inf, '1.8'):
            with self.assertRaises(ValueError):flux_density_limit(value)

    def test_all_regions_boundary_missing(self):
        run={'values':dict.fromkeys(IRON_FIELDS,1.8)}
        self.assertTrue(flux_density_review(run)['passed'])
        for field in IRON_FIELDS:
            trial=copy.deepcopy(run);trial['values'][field]=1.801
            self.assertFalse(flux_density_review(trial)['passed'])
            del trial['values'][field]
            self.assertIsNone(flux_density_review(trial)['passed'])
            self.assertIsNone(flux_density_review(trial)['maximum_T'])

    def test_saved_run_excess_and_request_validation(self):
        root=Path(__file__).resolve().parent
        request=json.loads((root/'requests/low_voltage.json').read_text(encoding='utf-8'))
        run=json.loads((root/'jobs/20261022_085158/r0_1_tune0.json').read_text(encoding='utf-8'))
        a=assess_run(run,request)
        self.assertAlmostEqual(a['flux_density']['maximum_T'],2.076)
        self.assertAlmostEqual(a['shortfalls']['flux_density_max_T'],.276)
        self.assertFalse(a['known_targets_met'])
        request['flux_density_max_T']=2.1
        self.assertTrue(assess_run(run,request)['flux_density']['passed'])
        run['values'].pop(IRON_FIELDS[0])
        self.assertIn('iron_flux_density',assess_run(run,request)['unverified_requirements'])
        request['flux_density_max_T']=0
        with self.assertRaises(ValueError):validate(request)


if __name__=='__main__':unittest.main()
