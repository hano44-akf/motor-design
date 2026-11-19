import math
import unittest
import numpy as np
from native_winding_review import review
from pathlib import Path
from spm_ripple import SPM_TYPES,radial_profile,derivative,predict,acceptance
from validate_spm_ripple import candidates

ROOT=Path(__file__).resolve().parent


def rectangle():
    pts=[(20,-5),(22,-5),(22,5),(20,5)]
    return {'centroid':{'x':21,'y':0},'entities':[{'type':'line','start':{'x':a[0],'y':a[1]},'end':{'x':b[0],'y':b[1]}} for a,b in zip(pts,pts[1:]+pts[:1])]}


class SPMRippleTests(unittest.TestCase):
    def test_native_boundary_ray_intersection(self):
        r=radial_profile(rectangle(),[0,.1,.8])
        self.assertAlmostEqual(r['thickness_mm'][0],2)
        self.assertAlmostEqual(r['thickness_mm'][1],2/math.cos(.1))
        self.assertEqual(r['thickness_mm'][2],0)

    def test_rotational_derivative_units(self):
        theta=np.arange(240)*2*math.pi/240
        self.assertLess(np.max(np.abs(derivative(np.sin(3*theta))-3*np.cos(3*theta))),1e-7)

    def test_acceptance_does_not_turn_absent_prediction_into_pass(self):
        self.assertEqual(acceptance(20,50)['state'],'passed')
        self.assertFalse(acceptance(20,50)['actual_20pct_passed'])
        self.assertEqual(acceptance(19,51)['state'],'failed')
        self.assertEqual(acceptance(100,10)['state'],'not_tested')
        self.assertEqual(acceptance(19,None)['state'],'unverified')

    def test_every_surface_type_uses_common_solver_without_certification(self):
        coils=review(ROOT/'baseline.mot')['coils']
        snapshot={'geometry_mm':{'Stator_Bore':52.3,'Stator_Lam_Length':20,'Slot_Opening':2,'Airgap':.5,'Magnet_Thickness':2.6},
            'poles':4,'slots':12,'connection':'delta','turns_per_coil':6,'line_peak_A':40,
            'coils':coils,'magnet_region':rectangle(),'magnet_br_T':1.4}
        for rotor in SPM_TYPES:
            r=predict({**snapshot,'rotor_id':rotor,'magnetisation':'Parallel' if rotor in ('surface_parallel','surface_flat') else 'Radial'},720,120)
            self.assertTrue(np.all(np.isfinite(r['torque_Nm'])))
            self.assertFalse(r['qualified']);self.assertEqual(r['calibration'],'none')
            self.assertIsNone(r['actual_ripple_pct'])

    def test_validation_plan_contains_four_types_and_no_fea_fitted_labels(self):
        p=candidates()
        self.assertEqual(p['scope'],list(SPM_TYPES));self.assertEqual(p['geometry_candidates'],64)
        self.assertEqual(p['maximum_fea_calls'],8)
        for group in p['groups']:
            self.assertEqual(len(group['cases']),16)
            for c in group['cases']:
                for value in c['geometry_mm'].values():self.assertAlmostEqual(value*10,round(value*10))
                self.assertGreaterEqual(c['geometry_mm']['Slot_Opening'],1.9)
                if c['rotor_id']=='surface_flat':
                    self.assertEqual(c['expected_native']['BPMRotor'],15)
                    self.assertIn('Magnet_Arc_[ED]',c['expected_native'])
                    self.assertNotIn('Magnet_Width',c['expected_native'])

    def test_fixed_derivative_bandwidth_does_not_change_with_sample_count(self):
        amplitudes=[]
        for n in (240,480,960):
            theta=np.arange(n)*2*math.pi/n
            amplitudes.append(float(np.max(derivative(np.sin(48*theta)))))
        self.assertLess(max(amplitudes)-min(amplitudes),1e-9)


if __name__=='__main__':unittest.main()
