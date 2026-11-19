import json
from pathlib import Path
import unittest
from review_spm_saturation import decode
from plan_spm_range_probe import make_plan

ROOT=Path(__file__).resolve().parent.parent


class SaturationReviewTests(unittest.TestCase):
    def test_dimensions_are_quantized_and_extrapolation_rejected(self):
        factors=[('tooth_width_mm',6.9,.6),('slot_depth_mm',10,.6),('slot_opening_mm',2,.4),('pole_arc_ed',120,10)]
        point,_=decode([.42,-.37,.12,0],factors)
        for key in ('tooth_width_mm','slot_depth_mm','slot_opening_mm'):self.assertAlmostEqual(point[key]*10,round(point[key]*10))
        with self.assertRaises(ValueError):decode([2,0,0,0],factors)

    def test_new_domain_pilot_is_not_a_surrogate_prediction(self):
        source=ROOT/'outputs/motorcad_spm_interaction_20261103_080325'
        if not source.exists():self.skipTest('Saved source missing')
        p=make_plan(source);self.assertEqual(p['planned_fea'],8);self.assertEqual(p['executed_fea'],0)
        self.assertEqual(p['flux_density_limit_T'],1.8)
        for group in p['groups']:
            self.assertEqual(len(group['cases']),4)
            for case in group['cases']:
                self.assertTrue(case['recipe']['ready_for_readback'])
                self.assertIsNone(case['performance_prediction'])
                self.assertFalse(case['recipe']['full_geometry_qualified'])


if __name__=='__main__':unittest.main()
