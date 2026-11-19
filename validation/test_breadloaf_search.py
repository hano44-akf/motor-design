import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from scipy.optimize import differential_evolution
from optimize_breadloaf_ripple import make_snapshot,run
from prepare_breadloaf_verification import prepare
from spm_ripple import predict

ROOT=Path(__file__).resolve().parent.parent


class BreadloafSearchTests(unittest.TestCase):
    def test_multistart_recomputes_initial_points_and_disables_relative_stop(self):
        seed=ROOT/'outputs/spm_ripple_recovery_20261103/surface_breadloaf_13_snapshot.json'
        with tempfile.TemporaryDirectory() as temp, patch('optimize_breadloaf_ripple.differential_evolution',wraps=differential_evolution) as de:
            result=run(seed,Path(temp)/'study',iterations=1,random_seeds=(11,22),initial_ticks=[[11,605,2]])
            self.assertEqual(de.call_count,2)
            for call in de.call_args_list:
                self.assertEqual(call.kwargs['tol'],0)
                self.assertEqual(call.kwargs['atol'],0)
            self.assertEqual([r['seed'] for r in result['optimizer_runs']],[11,22])
            self.assertEqual(result['plan']['initial_recomputed_candidates'],1)
            self.assertEqual(result['optimizer_nfev'],sum(r['nfev'] for r in result['optimizer_runs']))
            rows=json.loads((Path(temp)/'study/evaluations.json').read_text(encoding='utf-8'))
            self.assertIn([11,605,2],[r['ticks'] for r in rows])
            self.assertEqual(result['native_fea_calls'],0)

    def test_unreachable_target_returns_marked_best_effort_without_native(self):
        seed=ROOT/'outputs/spm_ripple_recovery_20261103/surface_breadloaf_13_snapshot.json'
        with tempfile.TemporaryDirectory() as temp:
            result=run(seed,Path(temp)/'study',target=100,max_current=1,iterations=1)
            self.assertEqual(result['selection_status'],'best_effort_current_limited')
            self.assertGreater(len(result['finalists']),0)
            for candidate in result['finalists']:
                last=candidate['levels'][-1]
                self.assertEqual(last['status'],'target_not_reached_within_current_limit')
                self.assertGreater(last['torque_shortfall_Nm'],0)
                self.assertLessEqual(last['line_peak_A'],1)
            self.assertEqual(result['native_fea_calls'],0)

    def test_candidate_does_not_mutate_native_seed(self):
        seed=json.loads((ROOT/'outputs/spm_ripple_recovery_20261103/surface_breadloaf_13_snapshot.json').read_text(encoding='utf-8'))
        before=json.dumps(seed,sort_keys=True)
        candidate=make_snapshot(seed,[11,605,2])
        self.assertEqual(json.dumps(seed,sort_keys=True),before)
        self.assertEqual(candidate['geometry_mm']['Slot_Opening'],1.1)
        self.assertEqual(candidate['expected_native']['MagnetReduction'],.2)
        self.assertNotIn('native_readback',candidate)
        self.assertEqual(candidate['expected_native']['BPMRotor'],2)

    def test_frozen_current_prediction_matches_recomputed_raw_model(self):
        study=ROOT/'outputs/breadloaf_shape_search_20261104'
        model=ROOT/'outputs/spm_ripple_validation_v2_20261103_140824/surface_breadloaf_13.mot'
        with tempfile.TemporaryDirectory() as temp:
            output=Path(temp)/'verification'
            plan=prepare(study,model,output)
            self.assertEqual(len(plan['cases']),3)
            for case in plan['cases']:
                s=json.loads((output/(case['id']+'_snapshot.json')).read_text())
                p=json.loads((output/(case['id']+'_proxy.json')).read_text())
                self.assertEqual(s['line_peak_A'],s['expected_native']['PeakCurrent'])
                self.assertEqual(p['calibration'],'none')
                self.assertFalse(p['optimization_eligible'])
                recomputed=predict(s,5760,960)
                np.testing.assert_allclose(p['torque_Nm'],recomputed['torque_Nm'],rtol=1e-10,atol=1e-10)


if __name__=='__main__':unittest.main()
