import json
from pathlib import Path
import tempfile
import unittest
from breadloaf_end_routing import arch,check_curves
from breadloaf_clearance_refinement import refine,build


def pair(gap):
    return [{'id':str(i),'end':'rear','coil_index':i,'phase':'AB'[i],
             'control_points_xyz_mm':arch([0,y],[20,y],5).tolist()} for i,y in enumerate((0,gap))]


class ClearanceRefinementTests(unittest.TestCase):
    def test_known_parallel_curves_resolve_both_sides(self):
        for gap,state in ((1.949,'confirmed_curve_conflict'),(1.951,'clear_with_error_bound')):
            routes=pair(gap);initial,_=check_curves(routes,1.95,16)
            self.assertEqual(initial['unresolved_pairs'],1)
            result=refine(routes,initial,1.95,error_target_mm=1e-6)
            row=result['refined_pairs'][0]
            self.assertEqual(row['state'],state)
            self.assertLessEqual(row['distance_lower_bound_mm'],gap+1e-12)
            self.assertGreaterEqual(row['distance_upper_bound_mm'],gap-1e-12)
            self.assertGreaterEqual(row['distance_lower_bound_mm'],initial['nonclear_pairs'][0]['distance_lower_bound_mm'])
            self.assertLessEqual(row['distance_upper_bound_mm'],initial['nonclear_pairs'][0]['distance_upper_bound_mm'])

    def test_exact_limit_is_not_passed_by_error_target(self):
        routes=pair(1.95);initial,_=check_curves(routes,1.95,16)
        result=refine(routes,initial,1.95,error_target_mm=.001)
        self.assertEqual(result['unresolved_pairs'],1)
        self.assertFalse(result['all_modelled_routes_clear'])
        self.assertEqual(result['refined_pairs'][0]['refinement_stop'],'error_target_reached_unresolved')

    def test_budget_and_interval_limits_do_not_force_resolution(self):
        routes=pair(1.95);initial,_=check_curves(routes,1.95,16)
        result=refine(routes,initial,1.95,pair_budget=1,error_target_mm=1e-12)
        self.assertEqual(result['pair_evaluations'],1)
        self.assertEqual(result['refined_pairs'][0]['refinement_stop'],'pair_budget_exhausted')
        limited=refine(routes,initial,1.95,max_intervals=16)
        self.assertEqual(limited['pair_evaluations'],0);self.assertEqual(limited['unresolved_pairs'],1)
        for kwargs in ({'pair_budget':True},{'max_intervals':8},{'error_target_mm':0}):
            with self.assertRaises(ValueError):refine(routes,initial,1.95,**kwargs)

    def test_existing_certificates_are_preserved_without_new_evaluations(self):
        for gap in (1,3):
            routes=pair(gap);initial,_=check_curves(routes,1.95,64)
            result=refine(routes,initial,1.95)
            self.assertEqual(result['pair_evaluations'],0)
            self.assertEqual(result['confirmed_conflicts'],initial['confirmed_conflicts'])
            self.assertEqual(result['all_modelled_routes_clear'],gap==3)

    def test_modified_upstream_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);up=root/'up.json';up.write_text('{}')
            (root/'transition_routing_review.json').write_text(json.dumps({'source_files':{str(up):'wrong'}}))
            with self.assertRaisesRegex(ValueError,'source changed'):build(root,persist=False)


if __name__=='__main__':unittest.main()
