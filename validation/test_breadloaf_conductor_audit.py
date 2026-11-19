import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_conductor_audit import boundary_margin,extract_saved,lattice_packing,build
from breadloaf_slot_detail import fields,dimensions

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'


class ConductorAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan=json.loads((DIRECT/'plan.json').read_text(encoding='utf-8'))
        cls.f=fields(plan['source_model']);cls.d=dimensions(cls.f)

    def test_finite_wire_disk_not_just_centre_must_fit(self):
        x=self.d['body_front_x']+.2
        self.assertLess(boundary_margin(self.d,[[x,0]],1.9)[0],0)
        with self.assertRaises(ValueError):boundary_margin(self.d,[[float('nan'),0]],1.9)
        with self.assertRaises(ValueError):boundary_margin(self.d,[[x,0]],0)

    def test_stale_cells_padding_and_placement_count_are_distinct(self):
        r=extract_saved(self.f,self.d)
        self.assertEqual(r['nonzero_saved_point_count'],79)
        self.assertEqual(r['boundary_compatible_raw_count'],10)
        self.assertEqual(r['declared_placement_count'],10)
        self.assertFalse(r['active_mask_confirmed']);self.assertFalse(r['phase_and_layer_mapping_confirmed'])
        f=dict(self.f);f['ConductorCentre_L_x[99][99]']='0';f['ConductorCentre_L_y[99][99]']='0'
        padded=extract_saved(f,self.d)
        self.assertEqual(padded['boundary_compatible_raw_count'],10)
        self.assertEqual(padded['zero_padding_count'],r['zero_padding_count']+1)

    def test_new_lattice_respects_whole_wire_and_pair_distances(self):
        r=lattice_packing(self.d,1.9,12,.05,.025)
        points=np.asarray(r['points_radial_tangential_mm'])
        self.assertTrue(np.all(boundary_margin(self.d,points,1.9)>=.025-1e-9))
        delta=np.linalg.norm(points[:,None,:]-points[None,:,:],axis=2);np.fill_diagonal(delta,np.inf)
        self.assertGreaterEqual(delta.min(),1.95-1e-9)
        self.assertFalse(r['failure_is_impossibility_proof']);self.assertFalse(r['native_winding_updated'])
        self.assertFalse(r['electrical_assignment_confirmed'])
        easy=lattice_packing(self.d,1.9,4,.05,.025,offset_steps=2)
        self.assertTrue(easy['geometric_target_found']);self.assertEqual(easy['selected_wire_count'],4)

    def test_invalid_packing_requests_rejected(self):
        for target in (0,-1,True,1.2):
            with self.assertRaises(ValueError):lattice_packing(self.d,1.9,target,.05,.025)
        with self.assertRaises(ValueError):lattice_packing(self.d,1.9,12,-.05,.025)

    def test_audit_does_not_assign_end_area_from_incomplete_coordinates(self):
        with patch('subprocess.Popen',side_effect=AssertionError('No Native launch')):r=build(DIRECT,persist=False)
        self.assertEqual(r['required_wires_per_slot'],12)
        self.assertFalse(r['saved_coordinates_match_required_count'])
        self.assertIsNone(r['conductor_derived_end_area_mm2'])
        self.assertFalse(r['physical_layer_mapping_confirmed']);self.assertFalse(r['qualified'])
        self.assertFalse(r['used_for_guidance']);self.assertEqual(r['new_native_fea'],0)
        end=r['end_input_audit']
        self.assertAlmostEqual(end['formula_coil_area_mm2'],13.291868793248401)
        self.assertLess(abs(end['relative_difference_pct']),.01)
        self.assertFalse(end['independent_new_geometry_prediction'])


if __name__=='__main__':unittest.main()
