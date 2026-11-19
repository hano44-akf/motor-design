import json
import math
import unittest
from pathlib import Path
from breadloaf_boundary import boundary
from magnet_boundary_check import check_region


class BreadloafBoundaryTests(unittest.TestCase):
    def test_matches_all_valid_saved_native_boundaries_and_rejects_crossings(self):
        root=Path(__file__).resolve().parent.parent/'outputs/spm_ripple_validation_v2_20261103_140824'
        paths=list(root.glob('surface_breadloaf_*_snapshot.json'))
        self.assertEqual(len(paths),16)
        valid=0
        for path in paths:
            s=json.loads(path.read_text(encoding='utf-8'));n=s['expected_native']
            args=(n['Stator_Bore'],n['Airgap'],n['Magnet_Thickness'],n['Magnet_Arc_[ED]'],n['MagnetReduction'])
            if not check_region(s['magnet_region'])['passed']:
                with self.assertRaises(ValueError):boundary(*args)
                continue
            actual,derived=boundary(*args);valid+=1
            self.assertGreater(derived['edge_thickness_along_magnet_axis_mm'],0)
            for a,b in zip(actual['entities'],s['magnet_region']['entities']):
                self.assertEqual(a['type'],b['type'])
                for field in ('start','end')+(('centre',) if a['type']=='arc' else ()):
                    for xy in ('x','y'):self.assertAlmostEqual(a[field][xy],b[field][xy],places=9)
                if a['type']=='arc':self.assertAlmostEqual(a['radius'],b['radius'],places=9)
        self.assertEqual(valid,5)

    def test_dimensions_and_rotated_axis(self):
        with self.assertRaises(ValueError):boundary(52.3,.5,2.5,140,.8)
        r,_=boundary(52.3,.5,2.5,70,.5,axis_rad=0)
        self.assertAlmostEqual(r['centroid']['y'],0)
        with self.assertRaises(ValueError):boundary(52.3,.5,2.5,float('nan'),.5)


if __name__=='__main__':unittest.main()
