import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_end_routing import segment_distance,bezier,arch,curve_statistics,check_curves,build

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'


class EndRoutingTests(unittest.TestCase):
    def test_segment_minimum_handles_crossing_parallel_and_degenerate_cases(self):
        self.assertAlmostEqual(segment_distance([[-1,0,0]],[[1,0,0]],[[0,-1,0]],[[0,1,0]]),0)
        self.assertAlmostEqual(segment_distance([[-1,0,0]],[[1,0,0]],[[0,-1,2]],[[0,1,2]]),2)
        self.assertAlmostEqual(segment_distance([[0,0,0]],[[1,0,0]],[[2,1,0]],[[3,1,0]]),np.sqrt(2))
        self.assertAlmostEqual(segment_distance([[0,0,0]],[[0,0,0]],[[1,-1,0]],[[1,1,0]]),1)

    def test_bezier_endpoints_peak_length_and_linearisation_bound(self):
        control=arch([0,0],[20,0],5)
        np.testing.assert_allclose(bezier(control,[0,1]),[[0,0,0],[20,0,0]])
        self.assertAlmostEqual(bezier(control,[.5])[0,2],5)
        stats=curve_statistics(control,32)
        self.assertGreater(stats['length_mm'],20)
        for i in range(32):
            t=(i+np.linspace(0,1,21))/32
            linear=stats['points'][i]+np.linspace(0,1,21)[:,None]*(stats['points'][i+1]-stats['points'][i])
            self.assertLessEqual(np.linalg.norm(bezier(control,t)-linear,axis=1).max(),stats['linearisation_error_bound_mm']+1e-12)
        refined=curve_statistics(control,64)
        self.assertAlmostEqual(refined['linearisation_error_bound_mm'],stats['linearisation_error_bound_mm']/4)
        self.assertAlmostEqual(refined['length_mm'],stats['length_mm'])

    def test_curve_conflict_and_clearance_are_distinguished_with_error_bounds(self):
        routes=[{'id':'a','end':'rear','control_points_xyz_mm':arch([0,0],[20,0],5).tolist()},
                {'id':'b','end':'rear','control_points_xyz_mm':arch([0,1],[20,1],5).tolist()}]
        result,_=check_curves(routes,1.95,32)
        self.assertEqual(result['confirmed_conflicts'],1);self.assertFalse(result['all_modelled_routes_clear'])
        routes[1]['control_points_xyz_mm']=arch([0,3],[20,3],5).tolist()
        result,_=check_curves(routes,1.95,32)
        self.assertTrue(result['all_modelled_routes_clear'])

    def test_invalid_curves_and_units_rejected(self):
        with self.assertRaises(ValueError):arch([0,0],[1,0],0)
        with self.assertRaises(ValueError):curve_statistics(arch([0,0],[1,0],1),True)
        with self.assertRaises(ValueError):bezier([[0,0,0]], [.5])

    def test_full_proposal_reports_conflicts_and_does_not_apply_resistance(self):
        with patch('subprocess.Popen',side_effect=AssertionError('No Native launch')):
            r=build(DIRECT,persist=False,intervals=16)
        self.assertEqual(r['route_count'],132);self.assertEqual([x['connection_count'] for x in r['ends']],[60,72])
        self.assertGreater(r['curve_clearance_check']['confirmed_conflicts'],0)
        self.assertFalse(r['end_routing_verified']);self.assertFalse(r['qualified']);self.assertEqual(r['new_native_fea'],0)
        self.assertIsNone(r['end_inductance_H']);self.assertIsNone(r['conductor_derived_end_area_mm2'])
        for phase in r['phase_length_diagnostics']:
            self.assertTrue(phase['omits_intercoil_links_and_terminals']);self.assertIsNone(phase['applied_phase_resistance_ohm'])
            self.assertAlmostEqual(phase['active_length_mm'],960)
        for route in r['routes']:
            z=route['control_points_world_xyz_mm'][0][2]
            self.assertAlmostEqual(z,-10 if route['end']=='front' else 10)


if __name__=='__main__':unittest.main()
