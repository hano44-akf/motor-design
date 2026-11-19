import unittest
import numpy as np
from audit_spm_ripple import compare, waveform_summary


class AuditTests(unittest.TestCase):
    def test_phase_cannot_hide_amplitude_error(self):
        t = np.arange(480) * 2 * np.pi / 480
        actual = .5 + .3 * np.sin(12 * t)
        prediction = .5 + .05 * np.sin(12 * t + np.pi / 2)
        r = compare(prediction, actual)
        self.assertAlmostEqual(r['mean_error_pct'], 0)
        self.assertAlmostEqual(r['peak_to_peak_underprediction_factor'], 6)
        self.assertGreater(r['best_shift_ac_rmse_Nm'], .17)
        self.assertFalse(r['phase_search_used_for_acceptance'])
        self.assertEqual(r['native']['dominant_mechanical_orders'][0]['order'], 12)

    def test_invalid_grids_and_nonfinite_samples_rejected(self):
        with self.assertRaises(ValueError):
            compare(np.ones(8), np.ones(9))
        with self.assertRaises(ValueError):
            waveform_summary([float('nan')] * 8)


if __name__ == '__main__':
    unittest.main()
