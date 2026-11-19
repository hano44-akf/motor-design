import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_leakage_geometry import hanselman,slot_energy_matrix,estimate,build,MU0

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'
STUDY=ROOT/'outputs/breadloaf_fine_search_20261105'


class LeakageGeometryTests(unittest.TestCase):
    def test_rectangular_slot_closed_form_energy(self):
        turns=7;length=.03;height=.01;width=.004;tip=.001;opening=.002
        L=slot_energy_matrix([[[turns,0,0]]],length,height,width,width,tip,opening)
        expected=MU0*length*turns**2*(height/(3*width)+tip/opening)
        self.assertAlmostEqual(L[0,0],expected,places=15)
        self.assertEqual(L[1,1],0)

    def test_mutual_sign_and_layer_scenarios_are_preserved(self):
        sides=[[[6,0,0],[0,-6,0]]]
        matrices=[slot_energy_matrix(sides,.02,.008,.006,.009,.0007,.0013,s) for s in ('mixed','listed_bottom_first','listed_top_first')]
        for L in matrices:
            self.assertLess(L[0,1],0)
            np.testing.assert_allclose(L,L.T,atol=1e-20)
            self.assertGreaterEqual(np.linalg.eigvalsh(L).min(),-1e-20)
        self.assertGreater(np.max(abs(matrices[1]-matrices[2])),1e-7)

    def test_turn_squared_length_and_opening_monotonicity(self):
        args=([[[6,0,0]]],.02,.008,.006,.009,.0007,.0013)
        base=slot_energy_matrix(*args)
        doubled=slot_energy_matrix([[[12,0,0]]],*args[1:])
        np.testing.assert_allclose(doubled,4*base)
        doubled_length=slot_energy_matrix(args[0],.04,*args[2:])
        np.testing.assert_allclose(doubled_length,2*base)
        wider=slot_energy_matrix(*args[:-1],.0026)
        self.assertLess(wider[0,0],base[0,0])

    def test_hanselman_formula_units_and_domain(self):
        expected=4*MU0*.03158*36/2*math.log(.03158*math.sqrt(math.pi)/(2*math.sqrt(13.291868793248401e-6)))
        self.assertAlmostEqual(hanselman(4,6,.03158,13.291868793248401e-6),expected,places=16)
        self.assertAlmostEqual(hanselman(4,12,.03158,13.291868793248401e-6),expected*4,places=16)
        for args in [(4,6,.001,.01),(4,0,.03,1e-5),(4,6,float('nan'),1e-5)]:
            with self.assertRaises(ValueError):hanselman(*args)

    def test_invalid_geometry_and_path_never_clipped(self):
        snapshot=json.loads((STUDY/'breadloaf_search_13_614_1_snapshot.json').read_text(encoding='utf-8'))
        s=copy.deepcopy(snapshot);s['paths']=2
        with self.assertRaises(ValueError):estimate(s,.25,.1)
        s=copy.deepcopy(snapshot);s['geometry_mm']['Slot_Depth']=.1
        with self.assertRaises(ValueError):estimate(s,.25,.1)
        s=copy.deepcopy(snapshot);s['coils'][0]['phase']=9
        with self.assertRaises(ValueError):estimate(s,.25,.1)

    def test_report_separates_formula_audit_from_independent_prediction(self):
        with patch('subprocess.Popen',side_effect=AssertionError('No Native launch')):r=build(DIRECT,STUDY,persist=False)
        self.assertEqual(len(r['rows']),3);self.assertEqual(r['new_native_fea'],0)
        self.assertFalse(r['qualified']);self.assertFalse(r['family_extension_allowed'])
        self.assertLess(abs(r['saved_cuboid_diagnostic']['relative_difference_pct']),.01)
        base=r['rows'][0]
        self.assertLess(base['native_comparison']['end_relative_difference_pct'],-10)
        self.assertTrue(all(x<-40 for x in base['native_comparison']['slot_balanced_relative_difference_pct']))
        self.assertIsNone(r['rows'][1]['native_comparison'])
        for row in r['rows']:
            for scenario in row['scenarios']:
                self.assertFalse(scenario['qualified']);self.assertFalse(scenario['used_for_guidance'])


if __name__=='__main__':unittest.main()
