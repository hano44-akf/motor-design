import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_flux_probe import wave_text,prepare,launch,review,resume_validated,pair_self_minimum

ROOT=Path(__file__).resolve().parent.parent


class FluxProbeTests(unittest.TestCase):
    def test_full_cycle_data_has_positive_self_derivatives_and_end_anchor(self):
        result=review(ROOT/'outputs/breadloaf_phase_mapping_full_20261105')
        self.assertEqual(result['status'],'central_jacobian_assembled')
        self.assertGreater(result['self_derivative_minimum_raw'],0)
        self.assertTrue(result['response_rows_excitation_columns_explicit'])
        anchor=result['unit_and_end_anchor']
        self.assertLess(anchor['max_H_interpretation_anchor_difference'],anchor['native_csv_rounding_H'])
        self.assertFalse(result['matrix_qualified']);self.assertFalse(result['pwm_ripple_certified'])

    def test_cycle_reconstruction_is_detected_before_more_pairs(self):
        root=ROOT/'outputs/breadloaf_phase_mapping_v3_20261105'
        load=lambda name:json.loads((root/name/'result.json').read_text(encoding='utf-8'))
        self.assertLess(pair_self_minimum(load('phase1_plus'),load('phase1_minus'),1),0)

    def test_angle_origin_correction_is_supported_by_solved_pilot_currents(self):
        root=ROOT/'outputs/breadloaf_phase_mapping_v2_20261105'
        plan=json.loads((root/'plan.json').read_text(encoding='utf-8'))
        result=json.loads((root/'phase1_plus/result.json').read_text(encoding='utf-8'))
        angle=np.array(plan['cases'][0]['expected_angle_ed']);file_values=np.array(plan['cases'][0]['expected_phase_current_A'])
        for phase in range(3):
            graph=result['graphs'][f'PhaseCurrent{phase+1}']
            expected=np.interp((np.array(graph['x'])-90)%360,angle,file_values[:,phase])
            np.testing.assert_allclose(graph['y'],expected,atol=1e-9)

    def test_stopped_input_check_cannot_produce_a_qualified_matrix(self):
        with tempfile.TemporaryDirectory() as tmp,patch('breadloaf_flux_probe.subprocess.Popen') as popen:
            folder=Path(tmp);(folder/'plan.json').write_text('{}')
            (folder/'result.json').write_text(json.dumps({'status':'stopped_after_input_check','completed_fea':1,'unattempted_cases':5}))
            result=review(folder)
            self.assertEqual(result['status'],'input_validation_incomplete')
            self.assertFalse(result['matrix_qualified']);self.assertEqual(result['new_native_fea'],0)
            popen.assert_not_called()

    def test_header_and_full_cycle_are_preserved(self):
        text=wave_text([0,180,360],[[1,2,3],[4,5,6],[1,2,3]])
        self.assertTrue(text.startswith('ElectricalAngle Phase1 Phase2 Phase3\n'))
        rows=np.loadtxt(text.splitlines(),skiprows=1)
        self.assertEqual(rows.shape,(3,4));self.assertEqual(rows[0,0],0);self.assertEqual(rows[-1,0],360)
        with self.assertRaises(ValueError):wave_text([0,359],[[1,2,3],[1,2,3]])

    def test_six_frozen_cases_perturb_only_the_selected_phase(self):
        with tempfile.TemporaryDirectory() as tmp,patch('breadloaf_flux_probe.subprocess.Popen') as popen:
            result=prepare(ROOT/'outputs/breadloaf_small_signal_20261105',Path(tmp)/'study')
            self.assertEqual(result['planned_fea'],6)
            self.assertEqual(result['settings']['DriveType_BPM'],0)
            self.assertEqual(result['settings']['BPMDriveMode'],2)
            self.assertEqual(result['settings']['FEASolutionCycle'],1)
            for phase in range(3):
                plus=np.array(result['cases'][phase*2]['expected_phase_current_A'])
                minus=np.array(result['cases'][phase*2+1]['expected_phase_current_A'])
                delta=np.zeros_like(plus);delta[:,phase]=.2
                np.testing.assert_allclose(plus-minus,delta,atol=1e-12)
                case=result['cases'][phase*2]
                expected_peak=np.max(abs(plus[:,0]-plus[:,1]))
                self.assertEqual(case['peak_line_current_setting_A'],expected_peak)
            popen.assert_not_called()

    def test_reuse_validated_cases_and_correct_only_phase3_normalisation(self):
        with tempfile.TemporaryDirectory() as tmp,patch('breadloaf_flux_probe.subprocess.Popen') as popen:
            r=resume_validated(ROOT/'outputs/breadloaf_phase_mapping_v3_20261105',Path(tmp)/'next')
            self.assertEqual(r['planned_fea'],2);self.assertEqual(len(r['reused_outcomes']),4)
            self.assertEqual({c['id'] for c in r['cases']},{'phase3_plus','phase3_minus'})
            for c in r['cases']:
                self.assertAlmostEqual(c['peak_line_current_setting_A'],39.9981243112972,places=8)
            popen.assert_not_called()

    def test_existing_batch_not_relaunched(self):
        with tempfile.TemporaryDirectory() as tmp,patch('breadloaf_flux_probe.subprocess.Popen') as popen:
            folder=Path(tmp);(folder/'progress.json').write_text('{}')
            with self.assertRaises(ValueError):launch(folder)
            popen.assert_not_called()


if __name__=='__main__':unittest.main()
