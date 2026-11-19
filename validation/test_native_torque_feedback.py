import unittest
from native_torque_feedback import propose_current


class FeedbackTests(unittest.TestCase):
    def test_local_proposal_not_claimed_verified(self):
        r=propose_current([{'line_peak_A':36.6,'torque_Nm':.46981}],.5,40)
        self.assertAlmostEqual(r['proposed_line_peak_A'],38.9519167323)
        self.assertTrue(r['within_current_limit']);self.assertTrue(r['native_verification_required'])
        self.assertFalse(r['qualified'])

    def test_current_limit_not_silently_clipped(self):
        r=propose_current([{'line_peak_A':40,'torque_Nm':.4}],.5,40)
        self.assertEqual(r['proposed_line_peak_A'],50)
        self.assertFalse(r['within_current_limit'])

    def test_secant_keeps_nonzero_intercept(self):
        r=propose_current([{'line_peak_A':20,'torque_Nm':.3},{'line_peak_A':30,'torque_Nm':.5}],.6,40)
        self.assertAlmostEqual(r['proposed_line_peak_A'],35)
        self.assertEqual(r['method'],'two_point_local_secant')

    def test_invalid_feedback_is_rejected(self):
        with self.assertRaises(ValueError):propose_current([],1,40)
        with self.assertRaises(ValueError):propose_current([{'line_peak_A':20,'torque_Nm':.5},{'line_peak_A':30,'torque_Nm':.3}],.6,40)


if __name__=='__main__':unittest.main()
