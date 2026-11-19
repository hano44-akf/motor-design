import copy
import json
from pathlib import Path
import unittest
import math
from result_review import review_result
from result_policy import candidate_rank,requirement,summarize_requirements

ROOT=Path(__file__).resolve().parent.parent


class ResultReviewTests(unittest.TestCase):
    def load(self,job):
        folder=ROOT/'validation/jobs'/job
        return folder,json.loads((folder/'result.json').read_text(encoding='utf-8'))

    def test_native_failures_and_unknowns_are_distinct_and_history_unchanged(self):
        folder,result=self.load('20261027_095545_502342500');before=copy.deepcopy(result)
        review=review_result(result,folder)
        self.assertEqual(result,before)
        self.assertEqual(review['motorcad_solves'],0)
        self.assertIsNone(review['best_available'])
        self.assertIsNotNone(review['best_diagnostic'])
        for c in review['candidates']:
            self.assertFalse(c['target_met'])
            for run in c['runs']:
                details={q['id']:q for q in run['requirements']}
                self.assertEqual(details['torque_ripple_max_pct']['state'],'violated')
                self.assertEqual(details['pwm_current_ripple']['state'],'unverified')
                self.assertIsNone(details['pwm_current_ripple']['shortfall'])
                self.assertEqual(details['dc_current_max_A']['state'],'not_applicable')
                self.assertIsNotNone(run['model_path'])
                emf=next(m for m in run['metrics'] if m['id']=='back_emf_phase_rms_V')
                raw=next(x for x in result['results'] if x['id']==c['id'])['runs'][0]
                self.assertAlmostEqual(emf['actual'],raw['values']['Back EMF Line-Line Voltage (peak) (fundamental)']/math.sqrt(2))

    def test_formula_only_cannot_be_certified_by_legacy_target_flag(self):
        folder,result=self.load('20261022_165707')
        review=review_result(result,folder)
        self.assertIsNone(review['best_available'])
        self.assertTrue(all(c['status']=='verification_incomplete' for c in review['candidates']))

    def test_smaller_known_shortfall_precedes_unknown_count_within_violation_class(self):
        a={'requirement_summary':summarize_requirements({'torque':requirement(.4,.5)})}
        small=candidate_rank([a],[{'known_normalized_shortfall':.1}])
        b={'requirement_summary':summarize_requirements({'torque':requirement(.4,.5),'PWM':requirement(None,15)})}
        smaller=candidate_rank([b],[{'known_normalized_shortfall':.05}])
        self.assertLess(smaller,small)


if __name__=='__main__':unittest.main()
