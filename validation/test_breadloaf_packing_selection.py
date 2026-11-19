import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from dimension_grid import resolution_policy,mm
from breadloaf_packing_selection import select
from breadloaf_continuous_packing import build

ROOT=Path(__file__).resolve().parent.parent
DIRECT=ROOT/'outputs/breadloaf_phase_mapping_full_20261105'


class PackingSelectionTests(unittest.TestCase):
    def test_selected_coordinates_preserve_precision_and_leave_physical_checks_open(self):
        source=json.loads((DIRECT/'continuous_packing_review.json').read_text(encoding='utf-8'))
        with patch('subprocess.Popen',side_effect=AssertionError('No Native')):r=select(DIRECT,persist=False)
        self.assertEqual(r['points_radial_tangential_mm'],source['best']['points_radial_tangential_mm'])
        self.assertFalse(r['coordinates_rounded']);self.assertTrue(r['geometric_check']['geometrically_verified'])
        self.assertFalse(r['whole_grid_diagnostic_required']);self.assertFalse(r['qualified'])
        self.assertFalse(r['electrical_assignment_confirmed']);self.assertFalse(r['end_path_verified'])
        self.assertFalse(r['native_winding_updated']);self.assertEqual(r['new_native_fea'],0)
        self.assertIsNone(r['conductor_derived_end_area_mm2'])

    def test_policy_keeps_input_rounding_and_disables_automatic_coordinate_grid_search(self):
        self.assertEqual(mm(1.25),1.3)
        self.assertEqual(resolution_policy()['design_length_step_mm'],.1)
        with patch('breadloaf_continuous_packing.repair_grid',side_effect=AssertionError('Unrequired grid search')):
            r=build(DIRECT,persist=False)
        self.assertEqual(r['coordinate_resolution_policy']['derived_coordinate_mode'],'continuous')
        self.assertFalse(r['grid_repair_required']);self.assertEqual(r['grid_repairs'],[])

    def test_changed_coordinates_fail_independent_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name in ('plan.json','continuous_packing_review.json'):(folder/name).write_bytes((DIRECT/name).read_bytes())
            path=folder/'continuous_packing_review.json';r=json.loads(path.read_text(encoding='utf-8'))
            r['best']['points_radial_tangential_mm'][0]=r['best']['points_radial_tangential_mm'][1]
            path.write_text(json.dumps(r),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'boundary check failed'):select(folder,persist=False)


if __name__=='__main__':unittest.main()
