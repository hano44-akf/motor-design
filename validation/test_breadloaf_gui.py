import tempfile
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import breadloaf_gui as gui


class GuiTests(unittest.TestCase):
    def test_live_elapsed_and_failed_cases_remain_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            (folder/'plan.json').write_text(json.dumps({'planned_fea':3,'cases':[]}))
            (folder/'progress.json').write_text(json.dumps({'status':'running','started_unix':100,'elapsed_s':0,
                                                          'completed_fea':1,'failed_cases':1}))
            with patch.object(gui,'LEGACY',{'live':('validation',folder)}),patch('breadloaf_gui.time.time',return_value=200):
                data=gui.detail('live')
            self.assertEqual(data['progress']['elapsed_s'],100)
            self.assertEqual(data['fea_counts'],{'required':3,'completed':1,'failed':1,'unresolved_required':2,'unattempted':1})

    def test_saved_read_never_launches_process(self):
        with patch('breadloaf_gui.subprocess.Popen') as popen:
            data=gui.detail('pilot-feedback')
            self.assertEqual(data['state'],'completed')
            self.assertAlmostEqual(data['rows'][0]['actual_ripple_pct'],13.683)
            self.assertFalse(data['production_optimizer_connected'])
            gui.jobs();popen.assert_not_called()

    def test_invalid_ids_and_targets_rejected(self):
        for job in ('../../validation',str(gui.ROOT),None):
            with self.assertRaises(ValueError):gui.locate(job)
        with patch('breadloaf_gui.subprocess.Popen') as popen:
            for target in (0,-1,float('nan'),True):
                with self.assertRaises(ValueError):gui.action('search',{'target_electromagnetic_torque_Nm':target})
            popen.assert_not_called()

    def test_selected_model_only_prepared_without_start(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(gui,'HOME',Path(temp)), patch('breadloaf_gui.subprocess.Popen') as popen:
            one=gui.detail('pilot-search')['rows'][0]['id']
            data=gui.action('prepare',{'id':'pilot-search','selected_ids':[one]})
            self.assertEqual(data['state'],'prepared')
            self.assertEqual([r['id'] for r in data['rows']],[one])
            from json import loads
            plan=loads((gui.locate(data['id'])[1]/'plan.json').read_text())
            self.assertEqual(plan['estimated_duration_minutes'],[2,4])
            self.assertEqual(plan['max_line_peak_A'],40)
            self.assertEqual(len(gui.jobs()['jobs']),len(gui.LEGACY)+1)
            popen.assert_not_called()
            with self.assertRaises(ValueError):gui.action('prepare',{'id':'pilot-search','selected_ids':['unknown']})
            with self.assertRaises(ValueError):gui.action('prepare',{'id':'pilot-search','selected_ids':[one,one]})

    def test_completed_feedback_not_repeated(self):
        with self.assertRaises(ValueError):gui.action('feedback',{'id':'pilot-validation'})
        with self.assertRaises(ValueError):gui.action('feedback',{'id':'pilot-feedback'})


if __name__=='__main__':unittest.main()
