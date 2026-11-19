import unittest
from refine_breadloaf_ripple import neighbours


class IntegerNeighbourTests(unittest.TestCase):
    def test_fixed_axes_and_edges_are_respected(self):
        bounds=((10,30),(614,614),(0,15))
        candidates=list(neighbours([10,614,0],bounds))
        self.assertEqual(set(candidates),{(11,614,0),(10,614,1)})

    def test_only_six_adjacent_points_not_full_grid(self):
        ticks=(15,600,5);bounds=((10,30),(400,1000),(0,15))
        candidates=list(neighbours(ticks,bounds))
        self.assertEqual(len(candidates),6)
        self.assertTrue(all(sum(abs(a-b) for a,b in zip(ticks,p))==1 for p in candidates))


if __name__=='__main__':unittest.main()
