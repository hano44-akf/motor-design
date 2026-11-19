import copy
import unittest
import numpy as np
from breadloaf_end_routing import bezier,curve_statistics,segment_distance
from breadloaf_transition_routing import elevate_septic,transition_controls,pair_metrics,accept_trial,optimise
from test_breadloaf_bundle_routing import examples


class TransitionRoutingTests(unittest.TestCase):
    def test_elevation_preserves_curve_and_two_derivatives(self):
        P=np.array(examples()[0]['control_points_xyz_mm']);Q=elevate_septic(P)
        for derivative in (0,1,2):
            np.testing.assert_allclose(bezier(P,np.linspace(0,1,80),derivative),bezier(Q,np.linspace(0,1,80),derivative),atol=1e-11)

    def test_transition_preserves_connections_endpoints_and_tangents(self):
        routes=examples();Q=transition_controls(routes,.5,1.5,2)
        for r,q in zip(routes,Q):
            P=np.array(r['control_points_xyz_mm'])
            for derivative in (0,1):np.testing.assert_allclose(bezier(P,[0,1],derivative),bezier(q,[0,1],derivative),atol=1e-12)
        self.assertFalse(np.allclose(Q[0],elevate_septic(routes[0]['control_points_xyz_mm'])))
        for args in ((.4,1,0),(1,1,3),(1,float('nan'),0)):
            with self.assertRaises(ValueError):transition_controls(routes,*args)

    def test_gate_rejects_hidden_relation_or_uncertainty_regression(self):
        old={'same_coil':{'confirmed':10,'unresolved':2},'different_phase':{'confirmed':20,'unresolved':5}}
        new=copy.deepcopy(old);new['same_coil']['confirmed']=11;new['different_phase']['confirmed']=0
        self.assertFalse(accept_trial(old,new))
        new=copy.deepcopy(old);new['same_coil']['confirmed']=9;new['same_coil']['unresolved']=3
        self.assertFalse(accept_trial(old,new))
        new=copy.deepcopy(old);new['same_coil']['confirmed']=9
        self.assertTrue(accept_trial(old,new));self.assertFalse(accept_trial(old,old))

    def test_metrics_distance_and_budget(self):
        routes=examples();a,b=[curve_statistics(r['control_points_xyz_mm'],32) for r in routes[:2]]
        error=a['linearisation_error_bound_mm']+b['linearisation_error_bound_mm']
        distance=segment_distance(a['points'][:-1],a['points'][1:],b['points'][:-1],b['points'][1:])
        confirmed,unresolved,penalty=pair_metrics(a,b,1.95)
        self.assertEqual(confirmed,int(distance+error<1.95))
        self.assertAlmostEqual(penalty,max(0,1.95-max(0,distance-error))**2)
        saved=copy.deepcopy(routes);trial,info=optimise(routes,1.95,budget=2,intervals=8)
        self.assertEqual(info['evaluations'],2);self.assertEqual(info['parameter_count'],3)
        self.assertEqual(routes,saved);self.assertEqual(len(trial[0]['control_points_xyz_mm']),8)
        with self.assertRaises(ValueError):optimise(routes,1.95,budget=True)


if __name__=='__main__':unittest.main()
