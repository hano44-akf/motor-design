import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_pwm_reference import simulate,review

ROOT=Path(__file__).resolve().parent.parent


class PWMReferenceTests(unittest.TestCase):
    def case(self):
        return {'inductance_H':(np.eye(3)*100e-6).tolist(),'phase_resistance_ohm':1e-4,
                'bus_V':12,'branch_reference_V':[3,-3,0],'switching_frequency_Hz':10000}

    def test_independent_scalar_check_without_preview_helpers(self):
        with patch('breadloaf_pwm_preview.periodic_ripple',side_effect=AssertionError('shared solver')), \
             patch('breadloaf_pwm_preview.switching_segments',side_effect=AssertionError('shared PWM')):
            r=simulate(self.case(),16384)
        expected=12*.25*.75/(2*100e-6*10000)
        one_step_current_bound=12/(100e-6*10000*16384)
        self.assertLess(abs(r['phase_ripple_pp_A'][0]-expected),one_step_current_bound)
        self.assertAlmostEqual(r['phase_ripple_pp_A'][2],0,places=9)
        self.assertLess(r['periodic_residual_A'],1e-8)
        self.assertFalse(r['qualified'])

    def test_invalid_delta_command_rejected(self):
        c=self.case();c['branch_reference_V']=[1,2,3]
        with self.assertRaisesRegex(ValueError,'KVL'):simulate(c)
        c=self.case();c['switching_frequency_Hz']=float('nan')
        with self.assertRaises(ValueError):simulate(c)

    def test_six_case_review_never_promotes_physical_qualification(self):
        original=json.loads((ROOT/'outputs/breadloaf_small_signal_20261105/pwm_preview.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'pwm_preview.json').write_text(json.dumps(original),encoding='utf-8')
            result=review(folder)
            self.assertEqual(len(result['cases']),6)
            self.assertEqual(result['new_native_fea'],0)
            self.assertFalse(result['physical_model_qualified']);self.assertFalse(result['matrix_orientation_resolved'])
            for c in result['cases']:
                self.assertLess(c['numerical_error_by_grid_A'][-1],c['numerical_error_by_grid_A'][0])
                self.assertEqual(c['runs'][-1]['steps_per_carrier'],65536)


if __name__=='__main__':unittest.main()
