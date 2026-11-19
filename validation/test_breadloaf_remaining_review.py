import copy
import json
from pathlib import Path
import unittest
from breadloaf_remaining_review import assess

ROOT=Path(__file__).resolve().parent.parent/'outputs/breadloaf_fine_verification_20261105'


class RemainingDriveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load=lambda p:json.loads(p.read_text(encoding='utf-8'))
        plan=load(ROOT/'plan.json');name=plan['cases'][0]['id']
        cls.contract=plan['request_contract'];cls.snapshot=load(ROOT/(name+'_snapshot.json'))
        cls.outcome=load(ROOT/name/'result.json')

    def test_other_voltages_stay_unverified_despite_ideal_headroom(self):
        result=assess(self.snapshot,self.outcome,self.contract)
        self.assertEqual([r['bus_V'] for r in result['voltage_screen']],[9,12,16])
        self.assertEqual([r['native_at_this_bus'] for r in result['voltage_screen']],[True,False,False])
        self.assertTrue(all(r['ideal_phasor_utilisation']<1 for r in result['voltage_screen']))
        self.assertTrue(all(not r['qualified'] for r in result['voltage_screen']))
        self.assertEqual(result['remaining_validation_item_count'],3)
        self.assertEqual(result['confirmed_additional_native_runs'],0)
        self.assertEqual(result['optional_same_current_voltage_runs'],2)
        self.assertFalse(result['automatic_fea_started'])

    def test_pwm_allowance_is_pp_over_winding_rms_not_delta_line_current(self):
        result=assess(self.snapshot,self.outcome,self.contract)
        pwm=result['pwm_reference']
        self.assertAlmostEqual(pwm['allowed_current_ripple_pp_A'],16.33*.15)
        self.assertIsNone(pwm['actual_current_ripple_pp_A']);self.assertIsNone(pwm['passed'])
        self.assertAlmostEqual(result['carrier_check']['switching_cycles_per_electrical_cycle'],10000/(3500*4/120))

    def test_missing_current_does_not_invent_zero_ripple(self):
        outcome=copy.deepcopy(self.outcome);outcome['values'].pop('Phase Current (rms)')
        result=assess(self.snapshot,outcome,self.contract)
        self.assertIsNone(result['pwm_reference']['allowed_current_ripple_pp_A'])
        self.assertIsNone(result['pwm_reference']['passed'])

    def test_wrong_winding_or_modulation_cannot_reuse_delta_limits(self):
        snapshot=copy.deepcopy(self.snapshot);snapshot['expected_native']['WindingConnection']=0
        with self.assertRaises(ValueError):assess(snapshot,self.outcome,self.contract)
        contract=copy.deepcopy(self.contract);contract['ui_input_snapshot']['modulation']='SPWM'
        with self.assertRaises(ValueError):assess(self.snapshot,self.outcome,contract)


if __name__=='__main__':unittest.main()
