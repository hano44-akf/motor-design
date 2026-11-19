import copy
import unittest
from verification_conditions import condition_plan,coverage,capacity_partner


class ConditionTests(unittest.TestCase):
    def request(self,margin=10):
        return {'temperatures_C':[20,80],'operating_point':{'voltages_V':[9,12,16],'torque_Nm':.5,'torque_margin_pct':margin}}

    def test_counts_and_targets(self):
        self.assertEqual(len(condition_plan(self.request(0))),6)
        plan=condition_plan(self.request());self.assertEqual(len(plan),12)
        self.assertEqual(len({p['condition_id'] for p in plan}),12)
        self.assertTrue(all(p['target_torque_Nm']==.55 for p in plan if p['role']=='capacity'))

    def test_coverage_rejects_missing_duplicate_and_wrong_conditions(self):
        r=self.request();runs=[{'verification_role':p['role'],'input_options':{'temperature_C':p['temperature_C']},'design':{'voltage_V':p['voltage_V']}} for p in condition_plan(r)]
        self.assertTrue(coverage(runs,r)['complete'])
        self.assertFalse(coverage(runs[:-1],r)['complete'])
        self.assertFalse(coverage(runs+[runs[0]],r)['complete'])
        wrong=copy.deepcopy(runs);wrong[1]['input_options']['temperature_C']=21
        self.assertFalse(coverage(wrong,r)['complete'])
        self.assertIsNone(capacity_partner(runs[0],wrong,r))
        self.assertIsNone(capacity_partner(runs[0],runs+[runs[1]],r))
        wrong=copy.deepcopy(runs);wrong[1]['design']['diameter_mm']=90
        self.assertIsNone(capacity_partner(runs[0],wrong,r))
