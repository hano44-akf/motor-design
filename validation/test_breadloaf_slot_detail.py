import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_slot_detail import dimensions,fields,body_width,native_width,area,detailed_slot,build

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'
STUDY=ROOT/'outputs/breadloaf_fine_search_20261105'


class SlotDetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads((DIRECT/'plan.json').read_text(encoding='utf-8'))
        cls.mot=Path(cls.plan['source_model']);cls.f=fields(cls.mot);cls.d=dimensions(cls.f)
        cls.regions=json.loads((cls.mot.parent/'native_geometry.json').read_text(encoding='utf-8'))['regions']
        cls.snapshot=json.loads(Path(cls.plan['source_snapshot']).read_text(encoding='utf-8'))

    def test_parametric_boundary_matches_native_lines_and_circular_base(self):
        for name,liner in [('StatorSlot',0),('Impreg_1',self.d['Liner_Thickness'])]:
            x=np.linspace(self.d['body_front_x']+.001,self.d['back_R']-liner-.001,41)
            for point in x:
                self.assertAlmostEqual(float(body_width(self.d,point,liner)),native_width(self.regions[name],point,self.d['beta']),places=8)
            self.assertAlmostEqual(area(self.d,liner),self.regions[name]['area'],places=8)

    def test_unsupported_topology_does_not_use_inactive_slot_width_fields(self):
        f=dict(self.f);f['Slot_Width']='99999';f['Slot_Width_Bottom']='99999'
        self.assertEqual(dimensions(f),self.d)
        for key,value in [('Slot_Type','Parallel_Slot'),('Slot_Corner_Radius','0.1'),('Tooth_Tip_Angle','90'),('Liner_Thickness','20')]:
            f=dict(self.f);f[key]=value
            with self.assertRaises(ValueError):dimensions(f)

    def test_layer_scenarios_preserve_energy_and_quadrature_stability(self):
        for scenario in ('mixed','listed_bottom_first','listed_top_first'):
            low=detailed_slot(self.snapshot,self.d,scenario,24)
            high=detailed_slot(self.snapshot,self.d,scenario,96)
            A=np.asarray(high['slot_matrix_H'])
            self.assertGreaterEqual(np.linalg.eigvalsh(A).min(),-1e-18)
            np.testing.assert_allclose(A,A.T,atol=1e-19)
            self.assertLess(abs(high['slot_balanced_mean_H']-low['slot_balanced_mean_H']),1e-10)
            self.assertFalse(high['qualified']);self.assertFalse(high['used_for_guidance'])

    def test_wrong_geometry_or_discretization_rejected(self):
        s=copy.deepcopy(self.snapshot);s['geometry_mm']['Slot_Opening']+=.1
        with self.assertRaisesRegex(ValueError,'mismatch'):detailed_slot(s,self.d,'mixed')
        with self.assertRaises(ValueError):detailed_slot(self.snapshot,self.d,'mixed',False)
        with self.assertRaises(ValueError):detailed_slot(self.snapshot,self.d,'unknown')

    def test_saved_geometry_checks_and_layer_ambiguity_are_not_family_approval(self):
        with patch('subprocess.Popen',side_effect=AssertionError('No new Native')):
            result=build(DIRECT,STUDY,persist=False)
        self.assertEqual(result['new_native_fea'],0);self.assertFalse(result['qualified'])
        self.assertFalse(result['family_extension_allowed'])
        self.assertEqual(len(result['saved_geometry_holdouts']),8)
        for row in [result['geometry_check']]+result['saved_geometry_holdouts']:
            self.assertLess(row['maximum_width_difference_mm'],1e-7)
            self.assertTrue(all(abs(v['difference_mm2'])<1e-7 for v in row['areas'].values()))
        self.assertFalse(result['layer_policy']['physical_layer_mapping_confirmed'])
        self.assertTrue(result['layer_policy']['thermal_cuboids_are_not_electrical_layers'])
        for new,old in zip(result['slot_scenarios'],result['previous_slot_estimates_H']):
            self.assertLess(abs(new['slot_balanced_mean_H']-result['native_slot_H']),abs(old-result['native_slot_H']))
        self.assertEqual(len(result['end_area_scenarios']),2)


if __name__=='__main__':unittest.main()
