import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from breadloaf_workflow import status, start, review
from prepare_breadloaf_current_feedback import prepare

ROOT=Path(__file__).resolve().parent.parent


class WorkflowTests(unittest.TestCase):
    def test_known_targets_met_with_unverified_items_does_not_request_current_correction(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);(folder/'plan.json').write_text('{}')
            report={'cases':[{'requirement_summary':{'passed':False,'known_requirements_passed':True},
                              'requirements':{'actual_ripple_20pct':{'state':'passed'}}}]}
            with patch('review_breadloaf_verification.review',return_value=report),patch('breadloaf_workflow.subprocess.Popen') as popen:
                r=review(folder)
                self.assertEqual(r['workflow']['next_action'],'resolve_remaining_verification')
                self.assertFalse(r['workflow']['strict_development_targets_passed'])
                popen.assert_not_called()

    def test_status_never_starts_native(self):
        with tempfile.TemporaryDirectory() as temp, patch('breadloaf_workflow.subprocess.Popen') as popen:
            self.assertEqual(status(temp)['progress']['status'],'prepared_not_started')
            popen.assert_not_called()

    def test_flat_batch_cannot_start(self):
        with tempfile.TemporaryDirectory() as temp, patch('breadloaf_workflow.subprocess.Popen') as popen:
            p=Path(temp);(p/'plan.json').write_text(json.dumps({'cases':[{'rotor_id':'surface_flat'}]}))
            with self.assertRaises(ValueError):start(p)
            popen.assert_not_called()

    def test_repeat_current_correction_blocked_without_output_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp);source=p/'source';source.mkdir();output=p/'next'
            (source/'plan.json').write_text(json.dumps({'schema':'breadloaf-local-current-feedback-v1'}))
            with self.assertRaisesRegex(ValueError,'budget exhausted'):prepare(source,output)
            self.assertFalse(output.exists())

    def test_small_residual_stays_visible_and_does_not_start_more_fea(self):
        p=ROOT/'outputs/breadloaf_current_feedback_20261104'
        with patch('breadloaf_workflow.subprocess.Popen') as popen:
            r=review(p)
            self.assertFalse(r['workflow']['strict_development_targets_passed'])
            self.assertEqual(r['workflow']['next_action'],'review_residual_correction_budget_exhausted')
            self.assertEqual(r['cases'][0]['requirements']['electromagnetic_torque']['state'],'violated')
            self.assertEqual(r['cases'][0]['current_feedback']['method'],'two_point_local_secant')
            self.assertEqual(r['before_after']['new_independent_geometry_cases'],0)
            popen.assert_not_called()


if __name__=='__main__':unittest.main()
