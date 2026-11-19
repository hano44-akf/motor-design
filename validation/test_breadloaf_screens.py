import math
import unittest
import numpy as np
from breadloaf_screens import evaluate


def fixture():
    n=240;t=np.arange(n)*2*np.pi/n;phases=t[:,None]+np.array([0,2*np.pi/3,4*np.pi/3])
    state={'reference_phase_current_A':np.cos(phases).tolist(),'pm_flux_linkage_Wb':(.1*np.sin(phases)).tolist(),
           'phase_inductance_H':np.repeat((np.eye(3)*.01)[None,:,:],n,axis=0).tolist(),
           'tooth_pm_flux_Wb':np.zeros((n,12)).tolist(),'tooth_armature_flux_Wb_per_A':np.zeros((n,12,3)).tolist()}
    proxy={'calibration':'none','electromagnetic_state':state,'cogging_Nm':[0]*n,'mutual_Nm':[.15]*n,'reluctance_Nm':[0]*n}
    s={'line_peak_A':math.sqrt(3),'poles':2,'expected_native':{'ShaftSpeed':60,'DCBusVoltage':12},
       'geometry_mm':{'Stator_Lam_Length':20,'Tooth_Width':8,'Stator_Lam_Dia':85,'Stator_Bore':52.3,'Slot_Depth':8.8}}
    ref={'phase_resistance_ohm':.1,'phase_leakage_inductance_H':.02,'stacking_factor':.97}
    return proxy,s,ref


class ScreenTests(unittest.TestCase):
    def test_voltage_includes_total_inductance_current_derivative(self):
        proxy,s,ref=fixture();r=evaluate(proxy,s,s['line_peak_A'],ref)
        expected=math.hypot(.1+2*math.pi*.1,2*math.pi*.03)/math.sqrt(2)
        self.assertAlmostEqual(r['phase_fundamental_voltage_rms_V'],expected,places=8)
        self.assertAlmostEqual(r['copper_loss_W'],.15)
        self.assertAlmostEqual(r['predicted_input_power_W'],r['electromagnetic_power_W']+r['copper_loss_W'],places=8)
        self.assertIsNone(r['efficiency_pct']);self.assertIsNone(r['local_peak_iron_B_T'])
        self.assertFalse(r['qualified'])

    def test_100pct_efficiency_excluded_by_copper_bound_but_unknowns_not_passed(self):
        proxy,s,ref=fixture()
        contract={'voltages_V':[.1],'requirements':{'efficiency_min_pct':100,'flux_density_max_T':1.8}}
        r=evaluate(proxy,s,s['line_peak_A'],ref,contract)
        self.assertEqual(r['checks']['efficiency_copper_only_upper_bound']['state'],'predicted_exceeds')
        self.assertEqual(r['checks']['fundamental_voltage']['state'],'predicted_exceeds')
        self.assertEqual(r['checks']['tooth_section_average_B']['state'],'not_excluded')
        self.assertNotIn('passed',{v['state'] for v in r['checks'].values()})

    def test_missing_saved_state_requires_recompute(self):
        self.assertFalse(evaluate({},None,1,None)['available'])
        p,s,r=fixture();r['phase_resistance_ohm']=-1
        with self.assertRaises(ValueError):evaluate(p,s,s['line_peak_A'],r)

    def test_inaccurate_section_B_does_not_reject_or_rank_candidates(self):
        p,s,r=fixture();p['electromagnetic_state']['tooth_pm_flux_Wb']=(np.ones((240,12))*.01).tolist()
        c={'voltages_V':[12],'requirements':{'flux_density_max_T':1.8}}
        result=evaluate(p,s,s['line_peak_A'],r,c)
        self.assertEqual(result['checks']['tooth_section_average_B']['state'],'predicted_exceeds')
        self.assertFalse(result['checks']['tooth_section_average_B']['used_for_guidance'])
        self.assertEqual(result['normalized_violation'],0)


if __name__=='__main__':unittest.main()
