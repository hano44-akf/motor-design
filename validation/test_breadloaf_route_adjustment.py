import unittest
import numpy as np
from breadloaf_end_routing import arch,bezier,curve_statistics
from breadloaf_route_adjustment import elevate,detour,search


class RouteAdjustmentTests(unittest.TestCase):
    def test_elevation_preserves_curve_and_derivatives(self):
        p=arch([0,0],[20,3],5);q=elevate(p);t=np.linspace(0,1,101)
        for derivative in range(3):
            np.testing.assert_allclose(bezier(p,t,derivative),bezier(q,t,derivative),atol=1e-12)

    def test_detour_preserves_endpoints_and_exit_tangents(self):
        p=elevate(arch([0,0],[20,3],5));q=detour(p,3,-2)
        for derivative in (0,1):
            np.testing.assert_allclose(bezier(p,[0,1],derivative),bezier(q,[0,1],derivative))
        self.assertFalse(np.allclose(bezier(p,[.5]),bezier(q,[.5])))
        for a,h in ((3.1,0),(0,4.1),(float('nan'),0)):
            with self.assertRaises(ValueError):detour(p,a,h)
        with self.assertRaises(ValueError):detour(elevate(arch([0,0],[20,0],.1)),0,-4)

    def test_quintic_interpolation_error_is_bounded(self):
        p=detour(elevate(arch([0,0],[20,0],5)),3,4);s=curve_statistics(p,32)
        u=np.linspace(0,1,31)
        for i in range(32):
            linear=s['points'][i]+u[:,None]*(s['points'][i+1]-s['points'][i])
            self.assertLessEqual(np.linalg.norm(bezier(p,(i+u)/32)-linear,axis=1).max(),s['linearisation_error_bound_mm']+1e-12)

    def test_budget_and_input_immutability(self):
        routes=[]
        for i,y in enumerate((0,1)):
            p=arch([0,y],[20,y],5).tolist()
            routes.append({'id':str(i),'end':'rear','control_points_xyz_mm':p,'control_points_world_xyz_mm':p})
        result,stats=search(routes,1.95,evaluation_budget=3)
        self.assertEqual(stats['evaluations'],3)
        self.assertLessEqual(stats['final_penalty'],stats['initial_penalty'])
        self.assertEqual(len(routes[0]['control_points_xyz_mm']),4)
        self.assertEqual(len(result[0]['control_points_xyz_mm']),6)
        self.assertFalse(stats['global_optimum_claimed'])
        with self.assertRaises(ValueError):search(routes,1.95,evaluation_budget=True)


if __name__=='__main__':unittest.main()
