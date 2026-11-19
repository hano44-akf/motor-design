import copy
import json
from pathlib import Path
import unittest
from rotor_catalog import catalog,resolve_rotor,manufacturing_rule,validate_parameters,preflight,require_execution,pole_slot_pairs
from geometry_adapters import build_geometry
from motorcad_adapter import variables
from low_voltage import configure

ROOT=Path(__file__).resolve().parent


class RotorCatalogTests(unittest.TestCase):
    def request(self):
        return json.loads((ROOT/'jobs/20261022_162610/request.json').read_text(encoding='utf-8'))

    def test_all_installed_rotors_registered_without_invented_sdk_ids(self):
        evidence=json.loads((ROOT/'automation/rotor_enum_evidence.json').read_text(encoding='utf-8'))
        names=max((r['items'] for r in evidence),key=len)
        self.assertEqual([r['label'] for r in catalog()['rotors']],names)
        self.assertEqual(len(names),16)
        self.assertTrue(all(r['motorcad_rotor_value'] is None for r in catalog()['rotors'][3:]))
        self.assertTrue(all(not r['design_qualified'] for r in catalog()['rotors']))
        self.assertFalse(catalog()['policy']['skew_enabled'])

    def test_legacy_ids_are_preserved_and_conflicting_ids_rejected(self):
        self.assertEqual(variables({'shape':'Radial','magnetisation':'Radial'})['BPMRotor'],0)
        self.assertEqual(resolve_rotor({'shape':'Surface Parallel'})['id'],'surface_parallel')
        with self.assertRaises(ValueError):resolve_rotor({'rotor_type':'spoke','shape':'Radial'})
        with self.assertRaises(ValueError):variables({'shape':'spoke','magnetisation':'Template'})

    def test_unknown_geometry_cannot_touch_motorcad_or_fall_back(self):
        class NoCalls:
            def load_from_file(self,*args):raise AssertionError('Unavailable rotor must not touch Motor-CAD')
        with self.assertRaisesRegex(ValueError,'Geometry adapter pending'):
            configure(NoCalls(),85,20,6,1.8,40,rotor_options={'shape':'spoke'})
        known=build_geometry({'shape':'Parallel'},85,20,{'Airgap':.5})
        self.assertEqual(known['Airgap'],.5)
        with self.assertRaises(ValueError):build_geometry({'shape':'Parallel'},85,20,{'Airgap':100})
        with self.assertRaises(ValueError):build_geometry({'shape':'Parallel'},85,20,{'unknown_geometry':1})

    def test_minimum_section_uses_actual_material_not_fixed_half_mm(self):
        request=self.request();rule=manufacturing_rule(request)
        self.assertEqual(rule['lamination_thickness_mm'],.5);self.assertEqual(rule['effective_minimum_mm'],.5)
        options={'shape':'interior_v_web','parameters':{'L1.bridge_thickness_mm':{'mode':'fixed','value':.4}}}
        with self.assertRaisesRegex(ValueError,'must be >= 0.5'):validate_parameters(options,rule)
        options['parameters']['L1.bridge_thickness_mm']['value']=.5
        validate_parameters(options,rule)
        request['manufacturing']={'lamination_thickness_mm':.7};thicker=manufacturing_rule(request)
        self.assertEqual(thicker['effective_minimum_mm'],.7)
        with self.assertRaisesRegex(ValueError,'must be >= 0.7'):validate_parameters(options,thicker)
        options['parameters']['L1.bridge_thickness_mm']['value']=.7;validate_parameters(options,thicker)
        request['manufacturing']={'lamination_thickness_mm':.55}
        self.assertEqual(manufacturing_rule(request)['grid_minimum_mm'],.6)
        request['manufacturing']={'lamination_thickness_mm':.3}
        with self.assertRaises(ValueError):manufacturing_rule(request)
        request['manufacturing']={'lamination_thickness_mm':.7}
        self.assertFalse(preflight(request)['executable'])  # old loss model must not silently serve new sheet thickness

    def test_parameter_isolation_grid_layer_and_excluded_skew(self):
        with self.assertRaises(ValueError):validate_parameters({'shape':'spoke','parameters':{'magnet_reduction_mm':{'mode':'fixed','value':.5}}})
        with self.assertRaises(ValueError):validate_parameters({'shape':'Breadloaf','parameters':{'magnet_reduction_mm':{'mode':'fixed','value':.55}}})
        options={'shape':'interior_v_web','parameters':{'magnet_layers':{'mode':'fixed','value':1},'L2.pole_v_angle_md':{'mode':'fixed','value':120.25}}}
        with self.assertRaisesRegex(ValueError,'Layer index exceeds'):validate_parameters(options)
        options['parameters']['magnet_layers']['value']=2
        validate_parameters(options)  # angles are not rounded as lengths
        with self.assertRaises(ValueError):validate_parameters({'shape':'Breadloaf','parameters':{'skew_deg':{'mode':'fixed','value':0}}})

    def test_pole_slot_combos_are_recorded_but_not_claimed_valid(self):
        request=self.request();request['pole_slot_candidates']=[{'poles':4,'slots':12},{'poles':10,'slots':12}]
        review=preflight(request)
        self.assertEqual(len(review['pole_slot_review']),2)
        self.assertFalse(review['executable']);self.assertFalse(any(r['winding_qualified'] for r in review['pole_slot_review']))
        with self.assertRaises(ValueError):require_execution(request)
        request['pole_slot_candidates']=[{'poles':18,'slots':12}]
        self.assertFalse(preflight(request)['pole_slot_review'][0]['pwm_check']['passes'])
        for pairs in ([],[{'poles':3,'slots':12}],[{'poles':4,'slots':12}]*2):
            with self.assertRaises(ValueError):pole_slot_pairs({'pole_slot_candidates':pairs})

    def test_registered_detailed_value_is_never_silently_ignored(self):
        request=self.request()
        self.assertTrue(require_execution(request)['executable'])
        request['spm']['parameters']={'pole_arc_ed':{'mode':'fixed','value':120}}
        with self.assertRaisesRegex(ValueError,'not optimized'):require_execution(request)
        request=self.request();request['skew_deg']=0
        with self.assertRaisesRegex(ValueError,'Skew is excluded'):preflight(request)
        request['spm']={'shape':'spoke','magnetisation':'Template'};request.pop('skew_deg')
        review=preflight(request)
        self.assertFalse(review['executable'])
        self.assertTrue(all(check['state']=='not_evaluated' for check in review['constraint_states']))


if __name__=='__main__':unittest.main()
