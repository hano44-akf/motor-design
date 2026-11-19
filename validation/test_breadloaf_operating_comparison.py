import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from breadloaf_operating_comparison import compare
from breadloaf_workflow import review

ROOT=Path(__file__).resolve().parent.parent
STUDY=ROOT/'outputs/breadloaf_shaft_search_20261105'
BATCH=ROOT/'outputs/breadloaf_shaft_verification_20261105'


class OperatingComparisonTests(unittest.TestCase):
    def batch_copy(self,folder):
        for name in ('plan.json','result.json','breadloaf_search_17_657_4_snapshot.json','breadloaf_search_17_657_4_proxy.json'):
            shutil.copyfile(BATCH/name,folder/name)

    def test_independent_errors_and_ripple_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.batch_copy(folder)
            report=compare(STUDY,folder);metrics=report['cases'][0]['metrics']
            self.assertAlmostEqual(metrics['shaft_torque_Nm']['prediction_minus_actual'],.00055,places=7)
            self.assertAlmostEqual(metrics['ripple_pct']['actual'],30.538)
            self.assertFalse(report['refit_performed']);self.assertEqual(report['new_native_fea'],0)
            decision=review(folder)
            self.assertEqual(decision['workflow']['next_action'],'revise_geometry_for_ripple')
            self.assertFalse(decision['workflow']['strict_development_targets_passed'])

    def test_different_current_cannot_be_compared_as_same_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.batch_copy(folder)
            path=folder/'breadloaf_search_17_657_4_snapshot.json'
            snapshot=json.loads(path.read_text(encoding='utf-8'));snapshot['line_peak_A']-=1
            path.write_text(json.dumps(snapshot),encoding='utf-8')
            plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
            plan['cases'][0]['snapshot_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
            (folder/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'current mismatch'):compare(STUDY,folder)
            self.assertFalse((folder/'operating_comparison.json').exists())

    def test_review_automatically_compares_the_frozen_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.batch_copy(folder)
            plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
            plan.update(source_search=str(STUDY),source_search_result_sha256=hashlib.sha256((STUDY/'result.json').read_bytes()).hexdigest())
            (folder/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
            review(folder)
            self.assertTrue((folder/'operating_comparison.json').is_file())
            plan['source_search_result_sha256']='changed'
            (folder/'plan.json').write_text(json.dumps(plan),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'source search changed'):review(folder)


if __name__=='__main__':unittest.main()
