import unittest
import numpy as np
from spm_ripple_operating_point import at_current, match_torque


class OperatingPointTests(unittest.TestCase):
    def proxy(self):
        t=np.arange(120)*2*np.pi/120
        return {'calibration':'none','cogging_Nm':(.1*np.sin(12*t)).tolist(),
                'mutual_Nm':(.5+.02*np.cos(12*t)).tolist(),
                'reluctance_Nm':(.01*np.cos(24*t)).tolist()}

    def test_current_scaling_preserves_cogging(self):
        p=self.proxy()
        np.testing.assert_allclose(at_current(p,40,0)['torque_Nm'],p['cogging_Nm'])
        expected=np.array(p['cogging_Nm'])+2*np.array(p['mutual_Nm'])+4*np.array(p['reluctance_Nm'])
        np.testing.assert_allclose(at_current(p,40,80)['torque_Nm'],expected)

    def test_match_and_current_limit(self):
        p=self.proxy();r=match_torque(p,40,.25,40)
        self.assertAlmostEqual(r['line_peak_A'],20)
        self.assertAlmostEqual(r['mean_Nm'],.25)
        self.assertFalse(r['optimization_eligible'])
        self.assertEqual(match_torque(p,40,1,40)['status'],'target_not_reached_within_current_limit')
        failed=match_torque(p,40,1,40)
        self.assertAlmostEqual(failed['mean_Nm'],.5)
        self.assertAlmostEqual(failed['torque_shortfall_Nm'],.5)
        self.assertEqual(failed['line_peak_A'],40)

    def test_quadratic_current_torque(self):
        p=self.proxy();p['reluctance_Nm']=[.1]*120
        r=match_torque(p,40,.6,40)
        self.assertAlmostEqual(r['line_peak_A'],40)
        self.assertAlmostEqual(r['mean_Nm'],.6)

    def test_calibrated_components_and_invalid_input_rejected(self):
        p=self.proxy();p['calibration']='component-fit'
        with self.assertRaises(ValueError):at_current(p,40,20)
        for value in (-1,float('nan')):
            with self.assertRaises(ValueError):match_torque(self.proxy(),40,value,40)


if __name__=='__main__':unittest.main()
