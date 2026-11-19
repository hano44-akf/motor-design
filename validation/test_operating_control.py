import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from operating_control import airgap_bounds,control_policy,solve_control
from motorcad_adapter import apply_checked
from motorcad_open import selected_model,queue_open


class ControlTests(unittest.TestCase):
    def model(self,**changes):
        return dict(torque_Nm=.5,speed_rpm=3500,pole_pairs=2,psi_Wb=.01,
                    ld_H=.0001,lq_H=.0001,resistance_ohm=.02,voltage_peak_V=20,**changes)

    def test_id0_and_nonsalient_mtpa_agree(self):
        a=solve_control(**self.model(),policy='ID0')
        b=solve_control(**self.model(),policy='MTPA')
        self.assertAlmostEqual(a['phase_peak_A'],.5/(3*.01))
        self.assertAlmostEqual(b['id_phase_peak_A'],0)
        self.assertAlmostEqual(a['phase_peak_A'],b['phase_peak_A'])

    def test_salient_mtpa_reduces_current_at_same_torque(self):
        m=self.model();m['lq_H']=.0003
        a=solve_control(**m,policy='ID0');b=solve_control(**m,policy='MTPA')
        self.assertLess(b['id_phase_peak_A'],0)
        self.assertLess(b['phase_peak_A'],a['phase_peak_A'])
        torque=3*(m['psi_Wb']+(m['ld_H']-m['lq_H'])*b['id_phase_peak_A'])*b['iq_phase_peak_A']
        self.assertAlmostEqual(torque,.5,places=7)

    def test_weakening_only_when_needed_and_checks_current(self):
        m=self.model();m['voltage_peak_V']=6
        a=solve_control(**m);b=solve_control(**m,field_weakening=True)
        self.assertFalse(a['voltage_passed']);self.assertTrue(b['feasible'])
        self.assertLess(b['id_phase_peak_A'],0);self.assertGreater(b['phase_advance_deg'],0)
        self.assertLess(b['model_evaluations'],150)
        c=solve_control(**m,field_weakening=True,current_peak_max_A=17)
        self.assertFalse(c['current_passed']);self.assertFalse(c['feasible'])
        d=solve_control(**self.model(),field_weakening=True)
        self.assertFalse(d['field_weakening_active'])

    def test_infeasible_weakening_returns_diagnostic(self):
        m=self.model();m['voltage_peak_V']=.01
        result=solve_control(**m,field_weakening=True)
        self.assertFalse(result['feasible']);self.assertTrue(math.isfinite(result['phase_peak_A']))

    def test_gap_default_grid_and_rejections(self):
        self.assertEqual(airgap_bounds({}),[.4,.6])
        self.assertEqual(airgap_bounds({'airgap_bounds_mm':[.5,.5]}),[.5,.5])
        self.assertEqual(airgap_bounds({'airgap_bounds_mm':[.41,.61]}),[.5,.6])
        for bounds in ([0,.6],[.6,.4],[.41,.49],[True,.6]):
            with self.assertRaises(ValueError):airgap_bounds({'airgap_bounds_mm':bounds})
        with self.assertRaises(ValueError):control_policy({'operating_point':{'current_control':'unknown'}})

    def test_motorcad_phase_advance_readback_without_launch(self):
        class Fake:
            def __init__(self):self.values={}
            def set_variable(self,k,v):self.values[k]=v
            def get_variable(self,k):return self.values[k]
        self.assertEqual(apply_checked(Fake(),{'phase_advance_deg':20})['PhaseAdvance'],20)

    def test_viewer_only_opens_selected_saved_comparison(self):
        with tempfile.TemporaryDirectory() as temp:
            jobs=Path(temp);folder=jobs/'20261022_000000';folder.mkdir()
            run={'label':'A_final','design':{'voltage_V':12},'input_options':{'temperature_C':20}}
            (folder/'A_final.mot').write_text('placeholder')
            result={'request':{'operating_point':{'voltages_V':[9,12,16]},'temperatures_C':[20]},'results':[{'id':'A','runs':[run]}]}
            (folder/'result.json').write_text(json.dumps(result))
            with patch('motorcad_open.JOBS',jobs):
                self.assertEqual(selected_model(folder,'A')[0].name,'A_final.mot')
                with self.assertRaises(ValueError):selected_model(folder,'A','../baseline')
                with self.assertRaises(ValueError):selected_model(folder,'unknown')
                with patch('motorcad_open.subprocess.Popen') as proc:
                    proc.return_value.pid=123
                    self.assertEqual(queue_open(folder,'A')['status'],'queued')
                    self.assertIn('A_final',proc.call_args.args[0])


if __name__=='__main__':unittest.main()
