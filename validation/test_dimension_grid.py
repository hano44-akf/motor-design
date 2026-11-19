import unittest
from dimension_grid import mm,wire_outer,grid_bounds


class GridTests(unittest.TestCase):
    def test_rounding_and_insulation(self):
        self.assertEqual(mm(1.25),1.3)
        self.assertEqual(mm(1.24),1.2)
        self.assertEqual(wire_outer(1.8),1.9)
        self.assertEqual(wire_outer(1.1),1.2)
    def test_bound_edges(self):
        self.assertEqual(grid_bounds([[55.01,55.29],[20,20],[2,2],[.81,1.09]]),[(551,552),(200,200),(2,2),(9,10)])
        with self.assertRaises(ValueError):grid_bounds([[55.01,55.09],[20,20],[2,2],[1,1]])


if __name__=='__main__':unittest.main()
