import json
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from scipy.optimize._numdiff import approx_derivative
from breadloaf_slot_detail import fields,dimensions
from breadloaf_continuous_packing import constraints,solve,verify_native_boundary,repair_grid,build

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'


class ContinuousPackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan=json.loads((DIRECT/'plan.json').read_text(encoding='utf-8'))
        mot=Path(plan['source_model']);cls.d=dimensions(fields(mot))
        cls.region=json.loads((mot.parent/'native_geometry.json').read_text(encoding='utf-8'))['regions']['Impreg_1']

    def test_analytic_jacobian_matches_independent_finite_difference(self):
        p=np.array([[30.,-.7],[32.,1.]])
        c,J=constraints(p,self.d,1.9,.05,.025)
        numerical=approx_derivative(lambda v:constraints(v.reshape(2,2),self.d,1.9,.05,.025)[0],p.ravel())
        np.testing.assert_allclose(J,numerical,atol=1e-7,rtol=1e-7)

    def test_independent_native_check_does_not_reuse_solver_constraints(self):
        p=[[30.,-1.],[33.,1.]]
        with patch('breadloaf_continuous_packing.constraints',side_effect=AssertionError('Shared constraints')):
            r=verify_native_boundary(p,self.region,self.d['beta'],1.9,.05,.025)
        self.assertTrue(r['geometrically_verified']);self.assertFalse(r['manufacturing_qualified'])
        r=verify_native_boundary([[30.,0.],[30.1,0.]],self.region,self.d['beta'],1.9,.05,.025)
        self.assertFalse(r['geometrically_verified']);self.assertLess(r['pair_constraint_slack_mm'],0)
        r=verify_native_boundary([[28.5,0.],[33.,1.]],self.region,self.d['beta'],1.9,.05,.025)
        self.assertFalse(r['geometrically_verified']);self.assertLess(r['boundary_constraint_slack_mm'],0)

    def test_milp_selects_valid_grid_points_without_changing_wire_size(self):
        r=repair_grid([[30.02,-1.02],[32.98,1.03]],self.d,1.9,.05,.025)
        self.assertTrue(r['found'])
        p=np.asarray(r['points_radial_tangential_mm']);np.testing.assert_allclose(p*10,np.round(p*10),atol=1e-12)
        checked=verify_native_boundary(p,self.region,self.d['beta'],1.9,.05,.025)
        self.assertTrue(checked['geometrically_verified']);self.assertFalse(r['native_winding_updated'])

    def test_budget_and_invalid_inputs(self):
        for target in (1,0,True,2.2):
            with self.assertRaises(ValueError):solve(self.d,target,1.9,.05,.025)
        with self.assertRaises(ValueError):solve(self.d,12,1.9,-.05,.025)
        with self.assertRaises(ValueError):repair_grid([[30.,0.],[33.,1.]],self.d,1.9,.05,.025,radius_ticks=0)

    def test_twelve_wire_report_separates_continuous_grid_and_electrical_status(self):
        with patch('subprocess.Popen',side_effect=AssertionError('No Native launch')):r=build(DIRECT,persist=False)
        self.assertEqual(r['target_wires'],12);self.assertEqual(r['free_coordinate_variables'],24)
        self.assertLessEqual(r['completed_starts'],r['restart_budget'])
        self.assertTrue(r['independent_native_boundary_check']['geometrically_verified'])
        self.assertFalse(r['grid_0p1mm_check']['geometrically_verified'])
        self.assertFalse(r['qualified']);self.assertFalse(r['physical_layer_mapping_confirmed'])
        self.assertFalse(r['native_winding_updated']);self.assertEqual(r['new_native_fea'],0)
        self.assertGreaterEqual(r['elapsed_s'],r['continuous_solve_elapsed_s'])
        for grid in r['grid_repairs']:self.assertFalse(grid['global_impossibility_proof'])


if __name__=='__main__':unittest.main()
