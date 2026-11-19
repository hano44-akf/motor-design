import math
from pathlib import Path
import unittest
from unittest.mock import patch
from native_winding_review import review
from mesh_review import mesh_levels

class NativeWindingTests(unittest.TestCase):
    def test_saved_native_layout_is_balanced_and_matches_with_convention_conversion(self):
        root=Path(__file__).resolve().parent.parent/'outputs/motorcad_batch_20261027_095545'
        for shape in ('radial','parallel'):
            r=review(root/(shape+'_diagnostics')/'native_winding.txt')
            self.assertTrue(r['balanced']);self.assertEqual(r['coil_span_slots'],[2])
            self.assertEqual(r['coils_per_phase'],[4,4,4]);self.assertEqual(r['slot_coil_side_counts'],[2]*12)
            self.assertIsNotNone(r['synthesized_layout_equivalence'])
            for kw in r['fundamental_winding_factors']:self.assertAlmostEqual(kw,math.sqrt(3)/2)

    def test_mesh_steps_align_with_angular_step(self):
        for p in (4,8,10):
            levels=mesh_levels(p,240)
            for level in levels:
                self.assertEqual(level['AirgapMeshPoints_mesh']%(240*(p//2)),0)
            self.assertEqual(levels[1]['MagnetMeshLength'],levels[0]['MagnetMeshLength']/2)

    def test_every_mesh_setting_is_checked_before_calculation(self):
        import low_voltage
        class IgnoredFirstSetting:
            def set_variable(self,key,value):pass
            def get_variable(self,key):return 2 if key=='TorqueNumberCycles' else 0
            def save_to_file(self,path):raise AssertionError('Ignored mesh setting must fail before save/solve')
        with patch('low_voltage.configure',return_value={}):
            with self.assertRaisesRegex(RuntimeError,'AirgapMeshPoints_mesh'):
                low_voltage.solve(IgnoredFirstSetting(),'not_run',85,20,6,1.8,40,
                    calculation_settings={'AirgapMeshPoints_mesh':480,'TorqueNumberCycles':2})

if __name__=='__main__':unittest.main()
