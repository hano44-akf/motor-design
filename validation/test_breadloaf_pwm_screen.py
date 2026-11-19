import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from breadloaf_pwm_screen import reference,evaluate,DIRECT
from breadloaf_screens import evaluate as model_screens
from test_breadloaf_screens import fixture


class PWMScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan=json.loads((DIRECT/'plan.json').read_text(encoding='utf-8'))
        cls.snapshot=json.loads(Path(plan['source_snapshot']).read_text(encoding='utf-8'))
        cls.contract=json.loads((Path(plan['source_batch'])/'plan.json').read_text(encoding='utf-8'))['request_contract']
        cls.ref=reference()

    def check(self,s=None,c=None,current=None):
        return evaluate(s or self.snapshot,self.snapshot['line_peak_A'] if current is None else current,c or self.contract,self.ref)

    def test_supported_point_margin_is_estimate_not_a_pass(self):
        with patch('subprocess.Popen',side_effect=AssertionError('Native forbidden')):r=self.check()
        self.assertTrue(r['available']);self.assertEqual(r['state'],'estimated_below_limit')
        self.assertAlmostEqual(r['rows'][-1]['margin_percentage_points'],.75553777456)
        self.assertFalse(r['used_for_guidance']);self.assertFalse(r['automatic_rejection'])
        self.assertIsNone(r['passed']);self.assertIsNone(r['model_error_bound_pct'])

    def test_stricter_target_excess_never_forces_rank_or_rejection(self):
        c=copy.deepcopy(self.contract);c['pwm_current_ripple_max_pct']=10
        r=self.check(c=c)
        self.assertEqual(r['state'],'estimated_exceeds')
        self.assertTrue(all(v['margin_A']<0 for v in r['rows']))
        self.assertEqual(r['normalized_violation'],0);self.assertFalse(r['automatic_rejection'])

    def test_each_changed_physical_condition_remains_unverified(self):
        for key in ('Slot_Opening','ShaftSpeed','Magnet_Temperature','MagTurnsConductor','WindingConnection','PhaseAdvance'):
            s=copy.deepcopy(self.snapshot);s['expected_native'][key]+=.1
            self.assertFalse(self.check(s=s)['available'],key)
        for key in ('coils','magnet_region','geometry_mm'):
            s=copy.deepcopy(self.snapshot);s[key]={}
            self.assertFalse(self.check(s=s)['available'],key)
        self.assertFalse(self.check(current=40)['available'])
        for key,value in [('core',['35PN230']),('modulation','SPWM'),('switchingKHz',20)]:
            c=copy.deepcopy(self.contract);c['ui_input_snapshot'][key]=value
            self.assertFalse(self.check(c=c)['available'],key)
        c=copy.deepcopy(self.contract);c['voltages_V']=[10]
        self.assertFalse(self.check(c=c)['available'])

    def test_missing_and_changed_source_never_reuses_stale_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(reference(tmp)['available'])
            folder=Path(tmp)
            for file in ('plan.json','pwm_preview.json','mapping_review.json'):(folder/file).write_bytes((DIRECT/file).read_bytes())
            (folder/'mapping_review.json').write_text('{}')
            self.assertFalse(reference(folder)['available'])

    def test_excluded_and_invalid_targets(self):
        for limit in (None,0,-1,float('nan'),True):
            c=copy.deepcopy(self.contract);c['pwm_current_ripple_max_pct']=limit
            r=self.check(c=c);self.assertFalse(r['available']);self.assertIsNone(r['passed'])
        c=copy.deepcopy(self.contract);c['voltages_V']=[16]
        self.assertEqual(len(self.check(c=c)['rows']),1)

    def test_optimizer_aggregate_does_not_gain_pwm_penalty(self):
        p,s,ref=fixture();ref['pwm_reference']=self.ref
        c=copy.deepcopy(self.contract)
        result=model_screens(p,s,s['line_peak_A'],ref,c)
        self.assertFalse(result['pwm_advisory']['available'])
        self.assertFalse(result['checks']['pwm_current_ripple']['used_for_guidance'])
        self.assertEqual(result['checks']['pwm_current_ripple']['normalized_violation'],0)


if __name__=='__main__':unittest.main()
