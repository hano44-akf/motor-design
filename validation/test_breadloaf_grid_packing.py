import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from breadloaf_grid_packing import candidate_grid,solve_grid
from breadloaf_slot_detail import fields,dimensions
from breadloaf_conductor_audit import boundary_margin

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'


class WholeGridTests(unittest.TestCase):
    def test_whole_supported_cavity_has_no_local_assignment_windows(self):
        plan=json.loads((DIRECT/'plan.json').read_text(encoding='utf-8'));d=dimensions(fields(plan['source_model']))
        ticks=candidate_grid(d,1.9,.025)
        self.assertEqual(len(ticks),2527)
        self.assertTrue(np.all(ticks==np.round(ticks)))
        self.assertTrue(np.all(boundary_margin(d,ticks/10,1.9)>=.025-1e-10))
        # Independent conservative rectangular enumeration reproduces the set;
        # no old wire centre or candidate label participates.
        box=np.array([[x,y] for x in range(280,351) for y in range(-100,101)])
        expected=box[boundary_margin(d,box/10,1.9)>=.025-1e-10]
        self.assertEqual(set(map(tuple,ticks)),set(map(tuple,expected)))

    def test_toy_grid_packing_has_exact_pair_separation(self):
        ticks=np.array([[0,0],[0,10],[30,0],[30,10]])
        with patch('subprocess.Popen',side_effect=AssertionError('Native forbidden')):
            r=solve_grid(ticks,2,1.95,time_budget_s=2)
        self.assertTrue(r['found_grid_packing'])
        p=np.array(r['points_radial_tangential_mm'])
        self.assertGreaterEqual(np.linalg.norm(p[0]-p[1]),1.95)
        self.assertFalse(r['manufacturing_qualified']);self.assertFalse(r['continuous_impossibility_proof'])

    def test_valid_clique_rejects_target_only_in_that_grid_model(self):
        r=solve_grid(np.array([[0,0],[0,10],[10,0]]),2,1.95,time_budget_s=2)
        self.assertFalse(r['found_grid_packing']);self.assertEqual(r['model_status'],'grid_relaxation_infeasible')
        self.assertTrue(r['cliques_validated_with_integer_distances'])
        self.assertLessEqual(r['maximum_clique_diameter_squared_ticks'],r['conflicting_distance_squared_ticks_max'])
        self.assertFalse(r['continuous_impossibility_proof'])

    def test_timeout_or_solver_error_never_becomes_impossibility(self):
        for status in (1,4):
            with patch('breadloaf_grid_packing.milp',return_value=SimpleNamespace(status=status,x=None,message='diagnostic')):
                r=solve_grid(np.array([[0,0],[30,0]]),2,1.95,time_budget_s=2)
            self.assertEqual(r['model_status'],'budget_or_solver_unresolved')
            self.assertFalse(r['continuous_impossibility_proof']);self.assertFalse(r['found_grid_packing'])

    def test_invalid_grid_and_budgets_rejected(self):
        for points in ([[0,.1],[20,0]],[[0,0],[0,0]],[[float('nan'),0],[20,0]]):
            with self.assertRaises(ValueError):solve_grid(points,2,1.95)
        with self.assertRaises(ValueError):solve_grid([[0,0],[20,0]],True,1.95)
        with self.assertRaises(ValueError):solve_grid([[0,0],[20,0]],2,1.95,time_budget_s=0)


if __name__=='__main__':unittest.main()
