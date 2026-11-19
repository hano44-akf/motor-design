import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from breadloaf_search_space import search_space
from breadloaf_request import adapt
from test_breadloaf_request import snapshot
from optimize_breadloaf_ripple import run

ROOT=Path(__file__).resolve().parent.parent


class SearchSpaceTests(unittest.TestCase):
    def test_mm_and_cm_sources_intersect_without_dropping_fixed_setting(self):
        s=snapshot();s.update(units='cm',geometry={},modes={'slotOpening':'range'},ranges={'slotOpening':{'min':.1,'max':.12}},
            statorParameters={'slot_opening_mm':{'mode':'fixed','value':1.1}},
            rotorParameters={'surface_breadloaf':{'pole_arc_ed':{'mode':'range','min':61,'max':62},'magnet_reduction_mm':{'mode':'fixed','value':.2}}})
        a=adapt(s);self.assertTrue(a['can_search'],a['errors'])
        space=a['search_space'];self.assertEqual(space['tick_bounds'],[(11,11),(610,620),(2,2)])
        self.assertEqual(space['free_variable_count'],1);self.assertEqual(space['full_grid_combinations'],11)
        self.assertEqual(len(space['variables'][0]['sources']),2)

    def test_conflicting_or_offgrid_fixed_values_rejected(self):
        with self.assertRaises(ValueError):search_space({'geometry':{'slotOpening':1.1},'statorParameters':{'slot_opening_mm':{'mode':'fixed','value':1.2}}})
        for value in (1.15,-1,True,float('nan'),4):
            with self.assertRaises(ValueError):search_space({'statorParameters':{'slot_opening_mm':{'mode':'fixed','value':value}}})
        with self.assertRaises(ValueError):search_space({'rotorParameters':{'surface_breadloaf':{'pole_arc_ed':{'mode':'range','min':70,'max':60}}}})

    def test_pole_arc_ratio_and_detailed_electrical_angle_agree(self):
        s={'geometry':{'poleArc':.35},'rotorParameters':{'surface_breadloaf':{'pole_arc_ed':{'mode':'fixed','value':63}}}}
        self.assertEqual(search_space(s)['tick_bounds'][1],(630,630))

    def test_all_fixed_evaluates_once_without_de_and_preserves_native_parameters(self):
        s=snapshot();s['statorParameters']={'slot_opening_mm':{'mode':'fixed','value':1.1}}
        s['rotorParameters']={'surface_breadloaf':{'pole_arc_ed':{'mode':'fixed','value':61.5},'magnet_reduction_mm':{'mode':'fixed','value':.2}}}
        contract=adapt(s);seed=ROOT/'outputs/spm_ripple_recovery_20261103/surface_breadloaf_13_snapshot.json'
        with tempfile.TemporaryDirectory() as temp,patch('optimize_breadloaf_ripple.differential_evolution') as de:
            r=run(seed,Path(temp)/'fixed',iterations=1,request_contract=contract)
            self.assertEqual(r['unique_candidates'],1);self.assertEqual(r['optimizer_nfev'],1)
            self.assertEqual(r['plan']['free_variable_count'],0)
            self.assertEqual(r['finalists'][0]['dimensions'],{'Slot_Opening':1.1,'Magnet_Arc_[ED]':61.5,'MagnetReduction':.2})
            de.assert_not_called()
            from prepare_breadloaf_verification import prepare
            from spm_ripple import predict
            import json
            import numpy as np
            model=ROOT/'outputs/spm_ripple_validation_v2_20261103_140824/surface_breadloaf_13.mot'
            batch=Path(temp)/'batch';plan=prepare(Path(temp)/'fixed',model,batch)
            name=plan['cases'][0]['id']
            s=json.loads((batch/(name+'_snapshot.json')).read_text())
            frozen=json.loads((batch/(name+'_proxy.json')).read_text())
            recomputed=predict(s,5760,960)
            np.testing.assert_allclose(frozen['electromagnetic_state']['reference_phase_current_A'],recomputed['electromagnetic_state']['reference_phase_current_A'],atol=1e-9)

    def test_one_free_parameter_only_evaluates_requested_ticks(self):
        s=snapshot();s['statorParameters']={'slot_opening_mm':{'mode':'range','min':1.1,'max':1.3}}
        s['rotorParameters']={'surface_breadloaf':{'pole_arc_ed':{'mode':'fixed','value':61.5},'magnet_reduction_mm':{'mode':'fixed','value':.2}}}
        contract=adapt(s);seed=ROOT/'outputs/spm_ripple_recovery_20261103/surface_breadloaf_13_snapshot.json'
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'range';r=run(seed,folder,iterations=1,request_contract=contract)
            import json
            rows=json.loads((folder/'evaluations.json').read_text())
            self.assertLessEqual(len(rows),3)
            for row in rows:
                self.assertIn(row['ticks'][0],(11,12,13));self.assertEqual(row['ticks'][1:], [615,2])
            self.assertEqual(r['plan']['grid_combinations_before_geometry_screen'],3)


if __name__=='__main__':unittest.main()
