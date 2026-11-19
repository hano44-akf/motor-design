"""Regression checks against saved FEA evidence; no Motor-CAD launch."""
import contextlib
import io
import json
import unittest
from acceptance import assess
from low_voltage import OUT
from optimize_low_voltage import optimize

class VoltageFallbackTests(unittest.TestCase):
    def test_saved_fea_and_target_change(self):
        result=json.loads((OUT/'A_final_12V.json').read_text(encoding='utf-8'))
        self.assertTrue(assess(result)['passed'])
        self.assertFalse(assess(result,95)['passed'])
        result['values']['Line-Line Terminal Voltage (peak)']=13
        self.assertIn('peak_voltage_within_bus',assess(result)['failures'])
        self.assertFalse(assess({})['passed'])

    def test_unmet_efficiency_returns_screened_best(self):
        with contextlib.redirect_stdout(io.StringIO()):
            result=optimize(efficiency_target=95,suffix='_voltage_fallback_95')
        self.assertEqual(result['status'],'best_effort_prediction')
        best=result['best_available_prediction']
        self.assertTrue(best['physical_screen_pass'])
        self.assertFalse(best['target_met'])
        self.assertLessEqual(best['estimated_terminal_peak_V'],9*.94)
        self.assertEqual(best['efficiency_pct'],max(p['efficiency_pct'] for p in result['predictions'] if p['physical_screen_pass']))

if __name__=='__main__':
    unittest.main()
