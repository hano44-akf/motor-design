import copy
import json
from pathlib import Path
import unittest
from controller_limits import pole_limit,switching_hz,inductance_voltage_upper,torque_ripple_limit,current_ripple_limit,current_ripple_review
from design_job import validate,assess_run

ROOT=Path(__file__).resolve().parent

class ControllerTests(unittest.TestCase):
    def test_default_and_even_pole_cap(self):
        for blank in [None,'']:
            self.assertEqual(switching_hz(blank),10000)
        self.assertEqual(pole_limit(3500)['max_even_poles'],16)
        self.assertTrue(pole_limit(3500,poles=16)['passes'])
        self.assertFalse(pole_limit(3500,poles=18)['passes'])
        self.assertEqual(pole_limit(3500,20000)['max_even_poles'],34)

    def test_twenty_is_inclusive(self):
        result=pole_limit(15000,poles=4)
        self.assertEqual(result['switching_cycles_per_electrical_cycle'],20)
        self.assertTrue(result['passes'])
        self.assertFalse(pole_limit(15000.01,poles=4)['passes'])

    def test_invalid_and_no_allowed_poles(self):
        for invalid in [0,-1,float('nan'),True]:
            with self.assertRaises(ValueError):switching_hz(invalid)
        self.assertEqual(pole_limit(3500,100)['max_even_poles'],0)
        req=json.loads((ROOT/'requests/low_voltage.json').read_text(encoding='utf-8'))
        req['switching_frequency_hz']=2000
        with self.assertRaises(ValueError):validate(req)

    def test_inductance_headroom_formula(self):
        run={'design':{'voltage_V':12},'readback':{'WindingConnection':1},'values':{
            'Back EMF Line-Line Voltage (peak) (fundamental)':4,
            'Phase Resistance':.01,'Phase Current (rms)':10,'Fundamental Frequency':100}}
        actual=inductance_voltage_upper(run,1)
        import math
        expected=math.sqrt((12/math.sqrt(2))**2-(4/math.sqrt(2)+.1)**2)/(2*math.pi*100*10)
        self.assertAlmostEqual(actual['Lq_upper_H'],expected)
        self.assertIsNone(actual['L_lower_H'])
        run['values']['Back EMF Line-Line Voltage (peak) (fundamental)']=20
        self.assertEqual(inductance_voltage_upper(run)['status'],'no_inductive_voltage_headroom')

    def test_actual_run_is_excluded_at_low_switching_frequency(self):
        run=json.loads((ROOT/'jobs/20261022_085158/R1-1_final_t0_v0.json').read_text(encoding='utf-8'))
        req=json.loads((ROOT/'requests/low_voltage.json').read_text(encoding='utf-8'))
        self.assertTrue(assess_run(run,req)['checks']['switching_cycles_at_least_20'])
        req['switching_frequency_hz']=2000
        self.assertFalse(assess_run(run,req)['checks']['switching_cycles_at_least_20'])

    def test_torque_ripple_cap_and_equality(self):
        self.assertEqual(torque_ripple_limit(None),20)
        with self.assertRaises(ValueError):torque_ripple_limit(20.01)
        run=json.loads((ROOT/'jobs/20261022_085158/R1-1_final_t0_v0.json').read_text(encoding='utf-8'))
        req=json.loads((ROOT/'requests/low_voltage.json').read_text(encoding='utf-8'))
        self.assertGreater(assess_run(run,req)['shortfalls']['torque_ripple_max_pct'],0)
        run['values']['Torque Ripple (MsVw) [%]']=20
        # Isolate the torque-ripple boundary from the new iron-flux requirement.
        from flux_limits import IRON_FIELDS
        for field in IRON_FIELDS:run['values'][field]=1.8
        self.assertTrue(assess_run(run,req)['known_targets_met'])
        self.assertFalse(assess_run(run,req)['target_met'])  # PWM waveform remains unverified.
        run['values']['Torque Ripple (MsVw) [%]']=20.01
        self.assertFalse(assess_run(run,req)['target_met'])

    def test_pwm_current_ripple_default_and_reference(self):
        self.assertEqual(current_ripple_limit(None),15)
        self.assertEqual(current_ripple_limit(''),15)
        for value in [0,-1,True,float('nan')]:
            with self.assertRaises(ValueError):current_ripple_limit(value)
        run={'values':{'Phase Current (rms)':10}}
        review=current_ripple_review(run)
        self.assertEqual(review['allowed_current_ripple_pp_A'],1.5)
        self.assertIsNone(review['passed'])
        self.assertIsNone(review['actual_current_ripple_pp_A'])
        self.assertEqual(current_ripple_review(run,10)['allowed_current_ripple_pp_A'],1)

if __name__=='__main__':unittest.main()
