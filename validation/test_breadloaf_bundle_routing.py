import copy
import unittest
import numpy as np
from breadloaf_end_routing import arch,bezier
from breadloaf_route_adjustment import elevate
from breadloaf_bundle_routing import corridor_controls,optimise


def examples():
    result=[]
    for i,y in enumerate((0,2,4)):
        p=elevate(arch([0,y],[20,y],8))
        result.append({'id':str(i),'end':'rear','coil_index':0,'phase':'A',
                       'from_conductor':str(i)+'a','to_conductor':str(i)+'b',
                       'control_points_xyz_mm':p.tolist(),'control_points_world_xyz_mm':p.tolist()})
    return result


class BundleRoutingTests(unittest.TestCase):
    def test_corridor_lanes_and_connections(self):
        routes=examples();P=corridor_controls(routes,1.95,lateral=2,height_delta=4)
        for r,q in zip(routes,P):
            p=np.array(r['control_points_xyz_mm'])
            for derivative in (0,1):np.testing.assert_allclose(bezier(p,[0,1],derivative),bezier(q,[0,1],derivative))
        for control in (2,3):
            np.testing.assert_allclose(np.linalg.norm(np.diff(P[:,control,:],axis=0),axis=1),1.95)
        self.assertTrue((P[:,:,2]>=0).all())

    def test_bounded_search_does_not_mutate_source(self):
        routes=examples();original=copy.deepcopy(routes)
        result,info=optimise(routes,1.95,budget=3)
        self.assertEqual(routes,original);self.assertEqual(info['evaluations'],3)
        self.assertEqual(info['parameter_count'],2)
        for old,new in zip(routes,result):
            self.assertEqual(old['id'],new['id'])
            np.testing.assert_array_equal(np.array(old['control_points_xyz_mm'])[[0,1,4,5]],np.array(new['control_points_xyz_mm'])[[0,1,4,5]])
            self.assertGreater(new['length_mm'],20)
        self.assertFalse(info['global_optimum_claimed'])

    def test_invalid_corridors_rejected(self):
        with self.assertRaises(ValueError):corridor_controls([],1.95)
        with self.assertRaises(ValueError):corridor_controls(examples(),float('nan'))
        with self.assertRaises(ValueError):corridor_controls(examples(),1.95,height_delta=-100)
        rows=examples();rows[0]['coil_index']=1
        with self.assertRaises(ValueError):corridor_controls(rows,1.95)
        with self.assertRaises(ValueError):optimise(examples(),1.95,budget=True)


if __name__=='__main__':unittest.main()
