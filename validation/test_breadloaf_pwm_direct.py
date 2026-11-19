import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_pwm_preview import direct_matrix,build
from breadloaf_pwm_reference import review

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'
EXPERIMENT=ROOT/'outputs/breadloaf_small_signal_20261105'
BATCH=ROOT/'outputs/breadloaf_fine_verification_20261105'


class DirectPWMTests(unittest.TestCase):
    def test_direct_total_matrix_has_no_added_end(self):
        source=json.loads((DIRECT/'mapping_review.json').read_text(encoding='utf-8'))
        L,evidence=direct_matrix(DIRECT,np.array(source['angle_ed']),'breadloaf_search_13_614_1')
        np.testing.assert_array_equal(L,source['matrix_native_flux_units_per_A'][:-1])
        self.assertEqual(evidence['end_added_H'],0)
        self.assertLess(evidence['closure_error_H'],evidence['native_csv_rounding_H'])

    def test_invalid_measurements_are_rejected(self):
        source=json.loads((DIRECT/'mapping_review.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            for name in ('plan.json','progress.json','mapping_review.json'):
                (folder/name).write_bytes((DIRECT/name).read_bytes())
            source['matrix_native_flux_units_per_A'][0][0][0]+=5.824e-6
            (folder/'mapping_review.json').write_text(json.dumps(source),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'anchor mismatch'):
                direct_matrix(folder,np.array(source['angle_ed']),'breadloaf_search_13_614_1')
            source['response_rows_excitation_columns_explicit']=False
            (folder/'mapping_review.json').write_text(json.dumps(source),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'validated explicit'):
                direct_matrix(folder,np.array(source['angle_ed']),'breadloaf_search_13_614_1')

    def test_direct_preview_and_independent_solver_keep_physical_status_open(self):
        with patch('subprocess.Popen',side_effect=AssertionError('Native must not launch')):
            result=build(EXPERIMENT,BATCH,angle_subdivisions=2,persist=False,direct_folder=DIRECT)
        self.assertTrue(result['matrix_orientation_resolved']);self.assertFalse(result['qualified'])
        self.assertEqual(result['unit_evidence']['end_added_H'],0)
        self.assertEqual(result['new_native_fea'],0)
        for row in result['rows']:
            self.assertIsNone(row['passed']);self.assertIsNone(row['actual_pwm_ripple_pp_A'])
            self.assertEqual(len(row['reference_cases']),1)
            self.assertNotIn('transposed_matrix_estimated_max_pp_A',row)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'pwm_preview.json').write_text(json.dumps(result),encoding='utf-8')
            checked=review(folder)
        self.assertEqual(len(checked['cases']),3)
        self.assertTrue(checked['matrix_orientation_resolved'])
        self.assertFalse(checked['physical_model_qualified'])
        for case in checked['cases']:
            self.assertLess(case['numerical_error_by_grid_A'][-1],case['numerical_error_by_grid_A'][0])


if __name__=='__main__':unittest.main()
