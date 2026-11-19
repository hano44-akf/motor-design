import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from breadloaf_end_routing import arch,check_curves,segment_distance
from breadloaf_route_conflicts import closest_witness,classify,build


class RouteConflictTests(unittest.TestCase):
    def test_witness_matches_segment_distance_and_lies_on_polylines(self):
        rng=np.random.default_rng(704)
        for _ in range(20):
            a=rng.normal(size=(6,3));b=rng.normal(size=(7,3))
            w=closest_witness(a,b)
            self.assertAlmostEqual(w['distance_mm'],segment_distance(a[:-1],a[1:],b[:-1],b[1:]),places=10)
            self.assertAlmostEqual(np.linalg.norm(np.array(w['a_xyz_mm'])-w['b_xyz_mm']),w['distance_mm'])
            for points,key in ((a,'a'),(b,'b')):
                index=w[key+'_t']*(len(points)-1);i=min(int(index),len(points)-2);t=index-i
                np.testing.assert_allclose(points[i]+t*(points[i+1]-points[i]),w[key+'_xyz_mm'],atol=1e-12)

    def test_parallel_degenerate_and_invalid(self):
        self.assertAlmostEqual(closest_witness([[0,0,0],[1,0,0]],[[0,2,0],[1,2,0]])['distance_mm'],2)
        self.assertAlmostEqual(closest_witness([[0,0,0],[0,0,0]],[[1,-1,0],[1,1,0]])['distance_mm'],1)
        with self.assertRaises(ValueError):closest_witness([[0,0,0]],[[0,0,0],[1,1,1]])

    def test_relation_totals_and_fixed_endpoint_warning(self):
        routes=[{'id':str(i),'end':'rear','coil_index':coil,'phase':phase,
                 'control_points_xyz_mm':arch([0,y],[20,y],5).tolist()}
                for i,(y,coil,phase) in enumerate(((0,0,'A'),(.5,0,'A'),(1,1,'A'),(1.5,2,'B')))]
        check,_=check_curves(routes,1.95,32);r=classify(routes,check,1.95)
        self.assertEqual(r['pair_count'],6)
        self.assertEqual(r['by_relation'],{'same_coil':1,'different_coil_same_phase':2,'different_phase':3})
        self.assertEqual(sum(x['pairs'] for x in r['groups']),6)
        self.assertEqual(r['fixed_endpoint_blocked_pairs'],6)
        self.assertEqual(sum(x['incident_pairs'] for x in r['route_priority']),12)
        check['nonclear_pairs'][0]['polyline_distance_mm']+=1
        with self.assertRaises(ValueError):classify(routes,check,1.95)

    def test_source_hash_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'upstream.json';source.write_text('{}')
            (root/'route_adjustment_review.json').write_text(json.dumps({'source_files':{str(source):'wrong'}}))
            with self.assertRaisesRegex(ValueError,'source changed'):build(root,persist=False)


if __name__=='__main__':unittest.main()
