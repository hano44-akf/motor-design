import unittest
import numpy as np
from analyze_detailed_spm import fit_audit,analyze
from pathlib import Path


class AnalysisTests(unittest.TestCase):
    def test_unseen_interaction_is_visible_only_on_holdouts(self):
        x=np.array([[0,0],[-1,0],[1,0],[0,-1],[0,1]])
        h=np.array([[.5,.5],[.5,-.5]])
        def response(v):return 2+v[:,0]+2*v[:,1]+4*v[:,0]*v[:,1]
        audit=fit_audit(x,response(x),h,response(h),True)
        self.assertAlmostEqual(audit['holdout_max_abs_error'],1)
        self.assertEqual(audit['training_residual_degrees_of_freedom'],0)
        self.assertFalse(audit['qualified_for_production'])

    def test_unidentifiable_training_is_rejected(self):
        with self.assertRaises(ValueError):fit_audit([[0],[0]],[1,1],[[.5]],[2],False)

    def test_saved_batch_is_auditable_without_native_sdk(self):
        source=Path(__file__).resolve().parent.parent/'outputs/motorcad_detailed_spm_20261027_143614'
        if not source.exists():self.skipTest('Saved native batch unavailable')
        data=analyze(source)
        self.assertEqual(len(data['source_sha256']),24)
        self.assertEqual(data['new_motorcad_solves'],0)
        for group in data['groups']:
            self.assertEqual(group['training_count'],9)
            self.assertEqual(group['holdout_count'],3)
            self.assertTrue(all(group['holdouts_outside_axial_training_convex_hull']))
            self.assertFalse(group['ripple_model_fitted'])
            self.assertFalse(group['production_model_activated'])


if __name__=='__main__':unittest.main()
