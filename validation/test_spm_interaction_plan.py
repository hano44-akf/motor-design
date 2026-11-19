from pathlib import Path
import unittest
from plan_spm_interaction import make_plan


class InteractionPlanTests(unittest.TestCase):
    def test_targeted_design_is_identifiable_and_new_holdouts_are_separate(self):
        root=Path(__file__).resolve().parent.parent
        source=root/'outputs/motorcad_detailed_spm_20261027_143614'
        if not source.exists():self.skipTest('Saved source unavailable')
        plan=make_plan(source)
        self.assertEqual(plan['planned_fea'],14)
        self.assertEqual(plan['executed_fea'],0)
        for group in plan['groups']:
            self.assertEqual(group['design_audit']['basis_rank'],10)
            self.assertEqual(group['design_audit']['residual_degrees_of_freedom'],3)
            self.assertEqual(sum(c['role']=='independent_holdout' for c in group['cases']),3)
            points=[tuple(sorted(c['point'].items())) for c in group['cases']]
            self.assertEqual(len(set(points)),7)
            for case in group['cases']:
                self.assertTrue(case['recipe']['ready_for_readback'])
                self.assertFalse(case['recipe']['performance_model_connected'])


if __name__=='__main__':unittest.main()
