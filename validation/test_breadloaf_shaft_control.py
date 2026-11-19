import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from breadloaf_shaft_control import solve,current_interval

ROOT=Path(__file__).resolve().parent.parent


class ShaftControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder=ROOT/'outputs/breadloaf_loss_B_validation_20261104'
        cls.s=json.loads((folder/'breadloaf_loss_B_H1_snapshot.json').read_text(encoding='utf-8'))
        cls.raw=json.loads((folder/'breadloaf_loss_B_H1_proxy.json').read_text(encoding='utf-8'))
        cls.model=json.loads((folder/'local_loss_B_model.json').read_text(encoding='utf-8'))

    def evaluator(self,proxy,snapshot,current,ref,contract):
        return {'local_calibrated_estimate':{'available':True,'shaft_torque_Nm':.1+.01*current}}

    def test_bounded_root_uses_shaft_torque_not_raw_em(self):
        with patch('breadloaf_shaft_control.evaluate',side_effect=self.evaluator):
            r=solve(self.raw,self.s,.495,40,{}, {},self.model)
        self.assertEqual(r['status'],'matched_shaft_in_local_model')
        self.assertAlmostEqual(r['line_peak_A'],39.5,places=6)
        self.assertAlmostEqual(r['predicted_shaft_torque_Nm'],.495)
        self.assertNotAlmostEqual(r['mean_Nm'],.495,places=3)
        self.assertFalse(r['qualified']);self.assertLess(r['shaft_control_evaluations'],20)

    def test_target_shortfall_within_current_and_domain(self):
        with patch('breadloaf_shaft_control.evaluate',side_effect=self.evaluator):
            r=solve(self.raw,self.s,.495,39,{}, {},self.model)
        self.assertEqual(r['status'],'shaft_target_not_reached_within_domain')
        self.assertLessEqual(r['line_peak_A'],39)
        self.assertAlmostEqual(r['shaft_torque_shortfall_Nm'],.005,places=6)

    def test_minimum_domain_current_can_exceed_minimum_torque_goal(self):
        interval=current_interval(self.model,self.s,40)
        with patch('breadloaf_shaft_control.evaluate',side_effect=self.evaluator):
            r=solve(self.raw,self.s,.4,40,{}, {},self.model)
        self.assertAlmostEqual(r['line_peak_A'],interval[0])
        self.assertGreater(r['predicted_shaft_torque_Nm'],.4)

    def test_outside_domain_never_claims_shaft_matching(self):
        s=copy.deepcopy(self.s);s['expected_native']['ShaftSpeed']=7000
        with patch('breadloaf_shaft_control.evaluate') as native:
            r=solve(self.raw,s,.5,40,{}, {},self.model)
            native.assert_not_called()
        self.assertEqual(r['status'],'shaft_matching_unverified')
        self.assertEqual(r['control_torque_basis'],'electromagnetic_lower_bound_only')


if __name__=='__main__':unittest.main()
