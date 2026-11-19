import copy
import json
from pathlib import Path
import unittest
import numpy as np
from breadloaf_local_model import fit,predict,operating_estimate,ROOT,TARGETS


class LocalModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=json.loads((ROOT/'outputs/breadloaf_loss_B_validation_20261104/paired_dataset.json').read_text(encoding='utf-8'))

    def test_holdout_targets_cannot_influence_fit_or_cv(self):
        a=fit(self.data['rows']);changed=copy.deepcopy(self.data['rows'])
        for row in changed:
            if not row['training_allowed']:
                for key in TARGETS:row['native'][key]*=100
        b=fit(changed)
        self.assertEqual(a['regularization'],b['regularization'])
        np.testing.assert_allclose(a['coefficients'],b['coefficients'])
        self.assertEqual(len(a['training_ids']),10)
        self.assertFalse(any('_H' in k or '_S' in k for k in a['training_ids']))

    def test_unsupported_speed_and_extrapolation_do_not_get_prediction(self):
        model=fit(self.data['rows']);row=copy.deepcopy(self.data['rows'][0])
        row['features']['PeakCurrent']=1
        self.assertFalse(predict(model,row)['available'])
        row['features']['ShaftSpeed']=7000
        self.assertFalse(predict(model,row,allow_extrapolation=True)['available'])

    def test_frozen_shape_checks_are_in_domain_but_not_qualified(self):
        model=fit(self.data['rows'])
        for row in self.data['rows']:
            if row['role']=='shape_holdout':
                result=predict(model,row)
                self.assertTrue(result['available']);self.assertTrue(result['inside_development_hull'])
                self.assertFalse(result['qualified'])
                self.assertTrue(all(v>0 for v in result['values'].values()))


if __name__=='__main__':unittest.main()
