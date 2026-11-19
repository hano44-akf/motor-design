import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from breadloaf_pwm_preview import switching_segments,periodic_ripple,build

ROOT=Path(__file__).resolve().parent.parent


class PWMPreviewTests(unittest.TestCase):
    def test_native_unit_closure_and_sensitive_16V_remain_unqualified(self):
        r=build(ROOT/'outputs/breadloaf_small_signal_20261105',ROOT/'outputs/breadloaf_fine_verification_20261105',angle_subdivisions=1,persist=False)
        self.assertLessEqual(r['unit_evidence']['closure_error_H'],r['unit_evidence']['rounding_allowance_H'])
        self.assertGreater(r['matrix_diagnostics']['with_end_symmetric_part_min_eigenvalue_H'],0)
        self.assertFalse(r['matrix_diagnostics']['symmetrisation_applied'])
        row=next(row for row in r['rows'] if row['bus_V']==16)
        self.assertEqual(row['preview_relation'],'orientation_sensitive_limit')
        self.assertIsNone(row['passed']);self.assertIsNone(row['actual_pwm_ripple_pp_A'])
        self.assertFalse(r['pwm_ripple_certified']);self.assertEqual(r['new_native_fea'],0)

    def test_bad_native_unit_evidence_is_rejected(self):
        with patch('breadloaf_pwm_preview.csv_number',return_value=(.05,'H',1e-5)):
            with self.assertRaisesRegex(ValueError,'Unexpected Native CSV units'):
                build(ROOT/'outputs/breadloaf_small_signal_20261105',ROOT/'outputs/breadloaf_fine_verification_20261105')

    def test_pwm_average_reproduces_delta_voltage(self):
        requested=np.array([4.,-1.,-3.]);duty,segments=switching_segments(requested,9)
        self.assertTrue(np.all((duty>=0)&(duty<=1)))
        np.testing.assert_allclose(sum(duration*error for duration,error in segments),np.zeros(3),atol=1e-12)
        self.assertAlmostEqual(sum(t for t,_ in segments),1)

    def test_lossless_scalar_limit_matches_independent_two_pulse_formula(self):
        # Two identical bus/zero pulses per carrier at this symmetric command.
        L=100e-6;bus=12;command=3;frequency=10000;d=command/bus
        expected=bus*d*(1-d)/(2*L*frequency)
        result=periodic_ripple(np.eye(3)*L,1e-4,bus,[command,-command,0],frequency)
        self.assertAlmostEqual(result['phase_ripple_pp_A'][0],expected,places=5)
        self.assertAlmostEqual(result['phase_ripple_pp_A'][2],0,places=9)
        self.assertLess(result['periodic_residual_A'],1e-8)

    def test_zero_reference_has_no_ideal_delta_switching_ripple(self):
        r=periodic_ripple(np.eye(3)*1e-4,.02,12,[0,0,0],10000)
        np.testing.assert_allclose(r['phase_ripple_pp_A'],[0,0,0],atol=1e-12)
        self.assertFalse(r['qualified'])

    def test_reject_invalid_kvl_and_unreachable_voltage_without_clipping(self):
        with self.assertRaisesRegex(ValueError,'KVL'):switching_segments([1,2,3],12)
        with self.assertRaisesRegex(ValueError,'outside'):switching_segments([20,-20,0],9)

    def test_nonpositive_energy_matrix_is_not_repaired(self):
        with self.assertRaisesRegex(ValueError,'no clipping'):
            periodic_ripple(np.diag([1e-4,1e-4,-1e-8]),.02,12,[2,-2,0],10000)


if __name__=='__main__':unittest.main()
