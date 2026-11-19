import copy
import json
from pathlib import Path
import tempfile
import unittest
from spm_geometry import preview,validate_settings
from model_capabilities import check_model_support
from verification_scope import apply_scope,POLICY
from task_store import TaskStore

ROOT=Path(__file__).resolve().parent.parent


class SPMGeometryTests(unittest.TestCase):
    def request(self,shape='Radial'):
        return {'spm':{'shape':shape,'magnetisation':'Parallel' if shape=='Parallel' else 'Radial'},
            'core':'POSCO | 50PN470','pole_slot_candidates':[{'poles':4,'slots':12}],
            'dimensions':{'diameter_mm':85,'length_mm':20}}

    def test_three_surface_types_have_explicit_unqualified_geometry(self):
        for shape in ('Radial','Parallel','Breadloaf'):
            result=preview(self.request(shape));d=result['designs'][0]
            self.assertTrue(d['envelope_checks_passed']);self.assertFalse(d['full_geometry_qualified'])
            self.assertFalse(result['optimization_connected'])
            for value in d['native_dimension_candidates'].values():self.assertAlmostEqual(value*10,round(value*10))
            self.assertAlmostEqual(d['derived_geometry']['stator_yoke_thickness_mm'],4.55)

    def test_fixed_and_range_dimensions_are_applied(self):
        r=self.request();r['geometry_parameters']={'slot_depth_mm':{'mode':'range','min':9,'max':11},'tooth_width_mm':{'mode':'fixed','value':6.5}}
        d=preview(r)['designs'][0]
        self.assertEqual(d['native_dimension_candidates']['Slot_Depth'],10)
        self.assertEqual(d['native_dimension_candidates']['Tooth_Width'],6.5)
        self.assertEqual(d['range_parameters'],1)
        self.assertAlmostEqual(d['derived_geometry']['stator_yoke_thickness_mm'],6.35)

    def test_interference_is_reported_without_inventing_performance(self):
        r=self.request();r['geometry_parameters']={'slot_depth_mm':{'mode':'fixed','value':20}}
        d=preview(r)['designs'][0];self.assertFalse(d['envelope_checks_passed']);self.assertIn('positive_yoke',d['violations'])
        self.assertNotIn('efficiency_pct',d)

    def test_breadloaf_reduction_is_not_claimed_as_corner_thickness(self):
        r=self.request('Breadloaf');r['spm']['parameters']={'magnet_reduction_mm':{'mode':'range','min':.2,'max':.8}}
        d=preview(r)['designs'][0];self.assertEqual(d['breadloaf_reduction_mm'],.5)
        self.assertIsNone(d['derived_geometry']['magnet_edge_thickness_mm'])
        self.assertIn('breadloaf_corner_geometry',d['native_mapping_pending'])
        r['spm']['parameters']={'magnet_reduction_mm':{'mode':'fixed','value':3}}
        self.assertFalse(preview(r)['designs'][0]['envelope_checks_passed'])

    def test_invalid_dimension_declarations_fail(self):
        for setting in ({'mode':'fixed','value':.55},{'mode':'fixed','value':True},{'mode':'range','min':5,'max':4},{'mode':'auto','value':2}):
            with self.assertRaises(ValueError):validate_settings({'slot_depth_mm':setting})
        with self.assertRaises(ValueError):validate_settings({'unknown':{'mode':'fixed','value':1}})

    def test_detailed_stator_inputs_cannot_be_ignored_by_old_optimizer(self):
        r=json.loads((ROOT/'validation/jobs/20261022_162610/request.json').read_text(encoding='utf-8'))
        r['geometry_parameters']={'slot_depth_mm':{'mode':'fixed','value':10}}
        support=check_model_support(r)
        self.assertFalse(support['supported']);self.assertTrue(any('stator geometry' in s for s in support['blocking_reasons']))

    def test_scope_removes_thermal_structure_but_retains_demagnetization(self):
        data=json.loads((ROOT/'outputs/topology_optimization_20261027/validation_queue.json').read_text(encoding='utf-8'))
        result=apply_scope(data)
        self.assertEqual(len(result['tasks']),88)
        self.assertEqual(len([t for t in result['tasks'] if t['id'].endswith('_demagnetization')]),11)
        self.assertFalse(any(t['id'].endswith('_safety') for t in result['tasks']))
        outputs=' '.join(str(t['required_outputs']) for t in result['tasks'])
        self.assertNotIn('stress and speed margin',outputs);self.assertNotIn('thermal boundary',outputs)
        self.assertEqual(result,apply_scope(result));self.assertEqual(result['verification_policy']['excluded'],POLICY['excluded'])

    def test_old_checklist_is_hidden_but_history_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=TaskStore(Path(tmp)/'tasks.sqlite')
            old=store.create('old',[{'id':'p4_s12_safety','kind':'manual_check','payload':{}}])
            new=store.create('new',[{'id':'p4_s12_demagnetization','kind':'manual_check','payload':{}}])
            self.assertEqual(store.supersede_outdated_checklists(new),[old])
            self.assertEqual(store.snapshot(old)['state'],'superseded')
            self.assertEqual([j['id'] for j in store.list_jobs()],[new])


if __name__=='__main__':unittest.main()
