import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from topology_study import run_study,geometry_draft

class TopologyStudyTests(unittest.TestCase):
    def request(self):
        return json.loads((Path(__file__).parent/'jobs/20261022_162610/request.json').read_text(encoding='utf-8'))

    def test_queue_dependencies_and_no_native_calls(self):
        r=self.request();r['pole_slot_candidates']=[{'poles':4,'slots':12},{'poles':10,'slots':12},{'poles':18,'slots':12}]
        with tempfile.TemporaryDirectory() as tmp, patch('topology_study.run_formula',side_effect=AssertionError('Plan must not optimize')),patch('low_voltage.configure',side_effect=AssertionError('No native calls')):
            out=Path(tmp)/'study';result=run_study(r,out,False)
            self.assertEqual(result['motorcad_solves'],0)
            self.assertEqual(result['pending_task_count'],16)
            self.assertEqual(result['topologies'][2]['status'],'excluded_by_analytical_screen')
            self.assertEqual(result['topologies'][1]['status'],'deferred_model_preparation')
            queue=json.loads((out/'validation_queue.json').read_text(encoding='utf-8'))
            seen=set()
            for task in queue['tasks']:
                self.assertTrue(set(task['depends_on'])<=seen);seen.add(task['id'])
                self.assertFalse(task['execution_enabled'])
            with self.assertRaises(FileExistsError):run_study(r,out,False)

    def test_new_topology_never_uses_existing_calibration(self):
        r=self.request();r['pole_slot_candidates']=[{'poles':8,'slots':12}]
        with tempfile.TemporaryDirectory() as tmp,patch('topology_study.run_formula',side_effect=AssertionError('Wrong calibration used')):
            result=run_study(r,Path(tmp)/'study')
            self.assertEqual(result['candidates'],[])
            self.assertFalse(result['all_topologies_optimized'])

    def test_geometry_is_grid_seed_not_verified(self):
        for q in (9,12,18,24):
            draft=geometry_draft(self.request(),{'poles':8,'slots':q})
            self.assertEqual(draft['status'],'unverified_geometry_seed')
            for v in draft['geometry_mm'].values():self.assertAlmostEqual(v*10,round(v*10))
            self.assertTrue(draft['tooth_plus_opening_below_bore_pitch'])

if __name__=='__main__':unittest.main()
