import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_coil_assignment import assign,envelope,path_check,build

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'


class CoilAssignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan=json.loads((DIRECT/'plan.json').read_text(encoding='utf-8'))
        cls.snapshot=json.loads(Path(plan['source_snapshot']).read_text(encoding='utf-8'))
        cls.points=json.loads((DIRECT/'selected_continuous_packing.json').read_text(encoding='utf-8'))['points_radial_tangential_mm']

    def test_slot_phase_sign_and_turn_graphs_preserve_source_winding(self):
        r=assign(self.snapshot,self.points,1.9,1.8)
        self.assertEqual(r['conductor_count'],144);self.assertEqual(r['slot_counts'],[12]*12)
        self.assertEqual(r['phase_counts'],[48]*3)
        self.assertEqual(len({(c['slot_zero_based'],c['point_index']) for c in r['conductors']}),144)
        expected=np.zeros((12,3),int)
        for c in self.snapshot['coils']:
            expected[c['start'],c['phase']]+=c['turns'];expected[c['end'],c['phase']]-=c['turns']
        np.testing.assert_array_equal(r['signed_slot_phase_counts'],expected)
        np.testing.assert_allclose(r['slot_lumped_fundamental_winding_factors'],[math.sqrt(3)/2]*3,atol=1e-12)
        for c in r['coils']:
            self.assertTrue(c['logical_path_check']['single_series_path']);self.assertEqual(c['logical_path_check']['visited_nodes'],24)
            self.assertEqual(c['active_conductor_segments'],12);self.assertEqual(len(c['end_connections']),11)
            self.assertEqual(sum(e['end']=='rear' for e in c['end_connections']),6)
            self.assertEqual(sum(e['end']=='front' for e in c['end_connections']),5)

    def test_coordinate_list_order_does_not_change_phasor_or_coverage(self):
        a=assign(self.snapshot,self.points,1.9,1.8);b=assign(self.snapshot,self.points[::-1],1.9,1.8)
        self.assertEqual(a['signed_slot_phase_counts'],b['signed_slot_phase_counts'])
        np.testing.assert_allclose([x['sum_end_chord_lower_bound_mm'] for x in a['coils']],
                                   [x['sum_end_chord_lower_bound_mm'] for x in b['coils']],atol=1e-10)

    def test_broken_branched_or_disconnected_coil_is_not_a_series_path(self):
        self.assertFalse(path_check(['a','b','c'],[('a','b'),('a','c')])['single_series_path'])
        self.assertFalse(path_check(['a','b','c','d'],[('a','b'),('c','d'),('d','c')])['single_series_path'])
        with self.assertRaises(ValueError):path_check(['a','b'],[('a','z')])

    def test_bundle_envelope_matches_circle_and_capsule_closed_forms(self):
        single=envelope([[0,0]],2)
        self.assertAlmostEqual(single['convex_wire_envelope_area_mm2'],math.pi)
        self.assertAlmostEqual(single['axis_aligned_envelope_area_mm2'],4)
        line=envelope([[0,0],[3,0]],2)
        self.assertAlmostEqual(line['convex_wire_envelope_area_mm2'],6+math.pi)
        with self.assertRaises(ValueError):envelope([[float('nan'),0]],2)

    def test_invalid_packing_or_coil_table_rejected(self):
        with self.assertRaises(ValueError):assign(self.snapshot,self.points[:-1],1.9,1.8)
        p=copy.deepcopy(self.points);p[0]=p[1]
        with self.assertRaises(ValueError):assign(self.snapshot,p,1.9,1.8)
        s=copy.deepcopy(self.snapshot);s['coils'][0]['phase']=9
        with self.assertRaises(ValueError):assign(s,self.points,1.9,1.8)
        with self.assertRaises(ValueError):assign(self.snapshot,self.points,1.8,1.9)

    def test_build_verifies_logic_without_promoting_physical_routing(self):
        with patch('subprocess.Popen',side_effect=AssertionError('No Native')):r=build(DIRECT,persist=False)
        self.assertTrue(r['logical_assignment_verified']);self.assertTrue(r['geometric_packing_verified'])
        self.assertFalse(r['physical_layer_mapping_confirmed']);self.assertFalse(r['end_routing_verified'])
        self.assertFalse(r['native_winding_updated']);self.assertFalse(r['qualified']);self.assertEqual(r['new_native_fea'],0)
        self.assertIsNone(r['conductor_derived_end_area_mm2'])
        for coil in r['coils']:
            for section in coil['bundle_geometry']:
                self.assertGreaterEqual(section['convex_wire_envelope_area_mm2'],coil['insulated_wire_area_per_coil_side_mm2']-1e-8)


if __name__=='__main__':unittest.main()
