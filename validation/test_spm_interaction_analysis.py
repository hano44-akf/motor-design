import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from analyze_spm_interaction import audit
from plan_spm_interaction import basis

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'outputs/motorcad_spm_interaction_20261103_080325'


class InteractionAnalysisTests(unittest.TestCase):
    def test_partial_batches_only_analyze_complete_topologies(self):
        if not SOURCE.exists():self.skipTest('Saved batch unavailable')
        review=audit(SOURCE)
        self.assertEqual(review['new_fea_started_by_analysis'],0)
        for group in review['groups']:
            self.assertEqual(group['training_count'],13)
            self.assertEqual(len(group['new_holdout_ids']),3)
            self.assertFalse(group['production_model_activated'])
            self.assertFalse(group['ripple_predictor_fitted'])
            for metric in group['metrics'].values():
                self.assertEqual(metric['augmented_additive_quadratic']['training_count'],13)
                self.assertEqual(metric['focused_interaction']['training_count'],13)
                self.assertTrue(all(not v['qualified'] for v in metric.values()))

    def test_changed_parent_plan_hash_rejected_before_results_used(self):
        if not SOURCE.exists():self.skipTest('Saved batch unavailable')
        plan=json.loads((SOURCE/'plan.json').read_text(encoding='utf-8'));plan['source_plan_sha256']='wrong'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Parent plan changed'):audit(path)

    def test_focused_basis_recovers_interaction_separately(self):
        axes=np.r_[np.zeros((1,4)),np.eye(4),-np.eye(4)]
        corners=np.array([[a,b,0,0] for a in (-1,1) for b in (-1,1)])
        x=np.r_[axes,corners];y=2+x[:,0]+3*x[:,0]*x[:,1]
        coef=np.linalg.lstsq(basis(x),y,rcond=None)[0]
        self.assertAlmostEqual(coef[-1],3)
        hold=np.array([[.5,.5,0,0]])
        self.assertAlmostEqual(float((basis(hold)@coef)[0]),3.25)


if __name__=='__main__':unittest.main()
