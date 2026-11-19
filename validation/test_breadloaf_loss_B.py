import json
from pathlib import Path
import tempfile
import unittest
from prepare_breadloaf_loss_B import prepare,material_audit,ROOT
from breadloaf_frequency_loss import predict
from breadloaf_loss_dataset import build


class LossBTests(unittest.TestCase):
    def test_frozen_roles_and_speed_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'batch';plan=prepare(folder)
            self.assertEqual(plan['planned_fea'],8);self.assertEqual(len({r['id'] for r in plan['cases']}),8)
            self.assertEqual(plan['roles'],{'development':4,'shape_holdout':2,'speed_check':2})
            self.assertEqual(sum(c['role']=='shape_holdout' for c in plan['cases']),2)
            for case in plan['cases']:
                snapshot=json.loads((folder/(case['id']+'_snapshot.json')).read_text())
                self.assertEqual(snapshot['rotor_id'],'surface_breadloaf')
                self.assertEqual(snapshot['line_peak_A'],snapshot['expected_native']['PeakCurrent'])
                self.assertIn(snapshot['expected_native']['ShaftSpeed'],(1750,3500,7000))

    def test_frequency_model_anchor_and_scope(self):
        source=ROOT/'outputs/breadloaf_current_feedback_20261104/result.json'
        v=json.loads(source.read_text(encoding='utf-8'))['outcomes'][0]['values']
        base=predict(v,3500);low=predict(v,1750);high=predict(v,7000)
        self.assertAlmostEqual(base['efficiency_pct'],v['System Efficiency'],delta=.02)
        self.assertAlmostEqual(high['copper_loss_W'],low['copper_loss_W'])
        self.assertGreater(high['iron_loss_components_W']['Stator tooth'],base['iron_loss_components_W']['Stator tooth'])
        self.assertFalse(base['qualified']);self.assertFalse(base['geometry_transfer_supported'])
        bad=dict(v);bad['Stator tooth Loss [excess] (on load)']=1
        with self.assertRaises(ValueError):predict(bad,7000)

    def test_material_frequency_limit_remains_explicit(self):
        audit=material_audit()
        self.assertGreater(len(audit['records']),0)
        for record in audit['records']:self.assertEqual(record['loss_frequencies_Hz'],[50.,60.])

    def test_holdout_not_used_for_training_and_failed_case_still_needed(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'batch';prepare(folder)
            source=ROOT/'outputs/breadloaf_current_feedback_20261104/result.json'
            row=json.loads(source.read_text(encoding='utf-8'))['outcomes'][0]
            row['id']='breadloaf_loss_B_H1'
            failed={'id':'breadloaf_loss_B_D1','rotor_id':'surface_breadloaf','status':'failed'}
            (folder/'partial_results.json').write_text(json.dumps([row,failed]))
            data=build(folder)
            self.assertIn(row['id'],data['excluded_from_training_ids'])
            self.assertNotIn(row['id'],data['training_ids'])
            self.assertEqual(data['counts']['existing_reused'],6)
            self.assertEqual(data['counts']['remaining_required_first_batch'],7)
            self.assertEqual(data['counts']['new_failed'],1)


if __name__=='__main__':unittest.main()
