"""Review regressions: real formula calls at fixed geometry, no Native solves."""
import contextlib
import copy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,MagicMock
from request_schema import normalize_request,domain_snapshot
from model_capabilities import check_model_support
from formula_job import run_formula,validate_formula
from operating_control import control_from_run
from study_io import export_job
from evaluation_policy import correction_factor
import rotor_catalog

ROOT=Path(__file__).resolve().parent


class ReviewFixTests(unittest.TestCase):
    def request(self):
        r=json.loads((ROOT/'jobs/20261022_132138/request.json').read_text(encoding='utf-8'))
        r['bounds']=[[85,85],[20,20],[6,6],[1.8,1.8]];r['airgap_bounds_mm']=[.5,.5]
        r['operating_point']['voltages_V']=[9,12,16]
        return r

    def formula(self,r):
        with tempfile.TemporaryDirectory() as folder,patch('low_voltage.start',side_effect=AssertionError('No Native')):
            return run_formula(r,Path(folder))

    def test_normalization_is_explicit_immutable_and_rotor_id_compatible(self):
        r=self.request();r.pop('temperatures_C');r['spm']={'rotor_type':'surface_radial'}
        r['operating_point']['voltages_V']=[16,9,12]
        before=copy.deepcopy(r);n=validate_formula(r)
        self.assertEqual(r,before);self.assertEqual(n['temperatures_C'],[20])
        self.assertEqual(n['spm']['shape'],'Radial');self.assertEqual(n['spm']['magnetisation'],'Radial')
        self.assertEqual(n['operating_point']['voltages_V'],[9,12,16])
        r['spm']={'rotor_type':'surface_parallel'}
        self.assertEqual(normalize_request(r)['spm']['magnetisation'],'Parallel')

    def test_blank_efficiency_is_inactive_and_dc_limit_is_predicted_unmet(self):
        r=self.request();r['operating_point'].update(efficiency_min_pct=None,dc_current_max_A=1)
        result=self.formula(r);c=result['results'][0];p=c['prediction'];review=c['formula_review']
        self.assertEqual(p['efficiency_requirement_state'],'not_requested')
        self.assertIsNone(p['efficiency_shortfall_percentage_points'])
        self.assertGreater(p['estimated_dc_current_A'],1)
        self.assertEqual(p['dc_current_requirement_state'],'predicted_unmet')
        self.assertFalse(review['predicted_all_active_met']);self.assertFalse(c['target_met'])
        active=review['conditions'][0]['requirements']
        self.assertEqual(active['efficiency_pct']['state'],'not_applicable')
        self.assertEqual(active['dc_current_max_A']['state'],'violated')
        self.assertIsNone(result['request']['operating_point']['efficiency_min_pct'])
        self.assertEqual(result['search_statistics']['prediction_computations'],1)
        self.assertGreater(result['search_statistics']['prediction_cache_hits'],0)

    def test_zero_efficiency_remains_an_explicit_target_and_other_conditions_unknown(self):
        r=self.request();r['operating_point']['efficiency_min_pct']=0
        c=self.formula(r)['results'][0]
        self.assertEqual(c['prediction']['efficiency_requirement_state'],'predicted_met')
        self.assertEqual(c['prediction']['efficiency_shortfall_percentage_points'],0)
        conditions=c['formula_review']['conditions'];self.assertEqual(len(conditions),3)
        self.assertFalse(conditions[1]['evaluated_by_formula'])
        self.assertEqual(conditions[1]['requirements']['torque_Nm']['state'],'unverified')
        self.assertFalse(c['formula_review']['verification_complete'])

    def test_high_request_is_not_presented_as_qualified_and_controller_is_separate(self):
        r=self.request();r['operating_point']['torque_Nm']=5
        review=check_model_support(r,'formula')
        self.assertTrue(review['supported']);self.assertEqual(review['model_validity']['state'],'unverified')
        self.assertFalse(review['model_validity']['independently_qualified'])
        r['operating_point']['speed_rpm']=20000
        review=check_model_support(r,'formula');self.assertFalse(review['supported'])
        self.assertFalse(review['controller_screens'][0]['passes'])

    def test_delta_adapter_rejects_star_and_six_step_snapshot_has_no_id0_claim(self):
        run=json.loads((ROOT/'jobs/20261022_132138/calibration.json').read_text(encoding='utf-8'))
        run['readback']['WindingConnection']=0
        with self.assertRaisesRegex(ValueError,'Delta'):control_from_run(run,self.request())
        r=self.request();r['control']='six_step'
        self.assertIsNone(domain_snapshot(r)['control']['current_control'])
        self.assertFalse(domain_snapshot(r)['control']['implemented'])

    def test_csv_keeps_native_mH_and_derived_H_distinct(self):
        r=self.request();run={'label':'B_final_t0_v0','values':{'D Axis Inductance':.02039},
            'design':{'voltage_V':9,'control_prediction':{'ld_H':.00002039}},'input_options':{'temperature_C':20}}
        result={'request':r,'status':'verification_incomplete','stage':'verification',
                'results':[{'id':'B','prediction':{},'runs':[run]}]}
        with tempfile.TemporaryDirectory() as d:
            export_job(Path(d),result)
            with (Path(d)/'motorcad.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        native=next(x for x in rows if x['field']=='values.D Axis Inductance')
        derived=next(x for x in rows if x['field']=='design.control_prediction.ld_H')
        self.assertEqual(native['unit'],'mH');self.assertEqual(derived['unit'],'H')
        self.assertIn('20degC_9V',native['condition_id']);self.assertEqual(native['evidence'],'saved_FEA')
        self.assertEqual(derived['evidence'],'formula_prediction')

    def test_zero_density_returns_diagnostic_candidates_instead_of_aborting(self):
        r=self.request();r['operating_point']['current_density_max_A_mm2']=0
        result=self.formula(r)
        self.assertTrue(result['results'])
        self.assertTrue(all(not c['physical_screens_pass'] for c in result['results']))
        self.assertTrue(all(c['formula_review']['predicted_all_active_met'] is False for c in result['results']))

    def test_capacity_margin_does_not_move_nominal_torque_or_claim_capacity(self):
        r=self.request();r['operating_point']['torque_margin_pct']=10
        c=self.formula(r)['results'][0]
        self.assertEqual(c['prediction']['estimated_shaft_torque_Nm'],.5)
        item=c['formula_review']['conditions'][0]['requirements']['capacity_torque_Nm']
        self.assertAlmostEqual(item['limit'],.55)
        self.assertEqual(item['state'],'unverified')

    def test_lamination_lookup_closes_connection_and_numerical_lower_bound_not_relaxed(self):
        db=MagicMock();db.execute.return_value.fetchall.return_value=[('0.0005','m')]
        rotor_catalog.material_lamination_thickness.cache_clear()
        with patch('rotor_catalog.sqlite3.connect',return_value=db):
            self.assertEqual(rotor_catalog.material_lamination_thickness('test-core')['value_mm'],.5)
        db.close.assert_called_once();rotor_catalog.material_lamination_thickness.cache_clear()
        self.assertGreater(correction_factor(.49,.5),1)
        self.assertEqual(correction_factor(.01,.5),1.5)
        with self.assertRaises(ValueError):correction_factor(0,.5)


if __name__=='__main__':unittest.main()
