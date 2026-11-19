import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_inductance_comparison import align_by_current,interpolate_cycles,diagnostics,build

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'
STUDY=ROOT/'outputs/breadloaf_fine_search_20261105'


class InductanceComparisonTests(unittest.TestCase):
    def test_alignment_uses_only_current_not_inductance_fit(self):
        angles=np.arange(720);phases=np.array([0,-120,120])
        current=lambda a:np.cos(np.radians(a[:,None]+phases))
        shift,error=align_by_current(angles,current(angles+37),angles[:360],current(angles[:360]))
        self.assertAlmostEqual(shift,-37);self.assertLess(error,1e-12)
        flipped=current(angles[:360])[:,[0,2,1]]
        with self.assertRaisesRegex(ValueError,'phase sequence'):align_by_current(angles,current(angles),angles[:360],flipped)

    def test_two_cycles_and_origin_interpolation_preserve_matrix(self):
        angles=np.arange(720);L=np.repeat(np.eye(3)[None,:,:],720,axis=0)
        L[:,0,0]=2+np.cos(np.radians(angles))
        result,spread=interpolate_cycles(angles,L,[0,90,180],90)
        np.testing.assert_allclose(result[:,0,0],[2,1,2],atol=1e-12)
        self.assertLess(spread,1e-12)
        with self.assertRaises(ValueError):interpolate_cycles(angles[:-1],L[:-1],[0],0)

    def test_balanced_projection_distinguishes_common_mode(self):
        L=np.repeat(np.eye(3)[None,:,:],5,axis=0)
        d=diagnostics(L+np.ones((3,3))*.2,L)
        self.assertAlmostEqual(d['maximum_entry_error_H'],.2)
        self.assertLess(d['balanced_subspace_error_spectral_max_H'],1e-15)

    def test_stale_preview_rejected_before_any_solver(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name in ('plan.json','pwm_preview.json','mapping_review.json'):(folder/name).write_bytes((DIRECT/name).read_bytes())
            (folder/'mapping_review.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'Stale'):build(folder,STUDY,persist=False)

    def test_saved_comparison_never_extends_family_or_clips_nullspace(self):
        # Full frozen-angle scalar/RK4 checks exercise the shared circuit solver
        # elsewhere. Stub only its cost here to exercise this adapter's units and
        # source guards without repeating thousands of exponentials.
        with patch('subprocess.Popen',side_effect=AssertionError('Native forbidden')), \
             patch('breadloaf_inductance_comparison.periodic_ripple',return_value={'phase_ripple_pp_A':[1.,2.,1.]}):
            report=build(DIRECT,STUDY,persist=False)
        self.assertFalse(report['family_extension_allowed']);self.assertFalse(report['qualified'])
        self.assertEqual(report['new_native_fea'],0);self.assertEqual(report['fitted_inductance_parameters'],0)
        self.assertEqual(report['rows'][0]['pwm_rows'],[])
        self.assertLess(report['rows'][0]['matrix_diagnostics']['common_mode_max_abs_H'],1e-15)
        original=next(r for r in report['rows'] if r['variant']=='existing_screen_active_plus_reference_leakage')
        self.assertAlmostEqual(original['matrix_diagnostics']['mean_self_H']-report['rows'][0]['matrix_diagnostics']['mean_self_H'],report['reference_leakage_H'])
        self.assertLessEqual(report['leakage_component_closure_error_H'],report['leakage_component_rounding_allowance_H'])
        self.assertLess(report['normalized_current_coefficient_error'],1e-12)


if __name__=='__main__':unittest.main()
