import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import formula_job
import verify_formula_job as verification

ROOT=Path(__file__).resolve().parent


class WorkflowTests(unittest.TestCase):
    def request(self):
        r=json.loads((ROOT/'jobs/20261022_132138/request.json').read_text(encoding='utf-8'))
        r['airgap_bounds_mm']=[.5,.5];r['bounds']=[[85,85],[20,20],[6,6],[1.8,1.8]]
        r['operating_point'].update(current_control='MTPA',field_weakening=True,voltages_V=[9,12])
        return r

    def test_formula_stage_never_launches_motorcad(self):
        with tempfile.TemporaryDirectory() as temp,patch('low_voltage.start',side_effect=AssertionError('Motor-CAD must not start')):
            r=formula_job.run_formula(self.request(),Path(temp))
            self.assertEqual(r['stage'],'formula');self.assertEqual(r['search_statistics']['motorcad_solves'],0)
            self.assertEqual(len(r['results']),1)
            self.assertEqual(r['results'][0]['design']['geometry_mm']['Airgap'],.5)
            self.assertTrue((Path(temp)/'inputs.csv').is_file())

    def test_shape_reference_cannot_silently_use_other_geometry(self):
        request=self.request();request['spm']={'shape':'Parallel','magnetisation':'Parallel'}
        with patch.object(formula_job,'PARALLEL_CALIBRATION',formula_job.CALIBRATION):
            with self.assertRaisesRegex(ValueError,'shape/direction mismatch'):formula_job.validate_formula(request)
        source=json.loads(formula_job.CALIBRATION.read_text(encoding='utf-8'))
        source['input_options'].update(shape='Parallel',magnetisation='Parallel')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'parallel.json';path.write_text(json.dumps(source))
            with patch.object(formula_job,'PARALLEL_CALIBRATION',path):
                self.assertEqual(formula_job.calibration_path(request),path)
                source['component_materials']['Magnet']='wrong material';path.write_text(json.dumps(source))
                with self.assertRaisesRegex(ValueError,'material mismatch'):formula_job.calibration_path(request)

    def test_selected_models_only_keep_geometry_and_apply_condition_controls(self):
        self.verify_selected()

    def test_capacity_point_is_separate_and_keeps_constraints_and_csv_context(self):
        self.verify_selected(margin=10)

    def test_capacity_and_nominal_correct_to_their_own_targets(self):
        self.verify_selected(margin=10,gain=.49)

    def verify_selected(self,margin=0,gain=.5025):
        template=json.loads((ROOT/'jobs/20261022_132138/calibration.json').read_text(encoding='utf-8'))
        calls=[]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'jobs/20261022_000000';source.mkdir(parents=True)
            request=self.request()
            request['operating_point']['torque_margin_pct']=margin
            if margin:request['operating_point'].update(current_control='ID0',field_weakening=False)
            model={'objective':'balanced','prediction':{'efficiency_pct':90},
                'design':{'diameter_mm':85,'length_mm':20,'turns_per_coil':6,'wire_diameter_mm':1.8,
                    'airgap_mm':.5,'geometry_mm':{'Airgap':.5},'input_peak_current_A':40.,'phase_advance_deg':0.}}
            formula={'stage':'formula','request':request,'results':[dict(model,id='A'),dict(model,id='B')],
                'search_statistics':{'design_dimensions':5},'effective_airgap_bounds_mm':[.5,.5],
                'timings':{'optimization_compute_s':.5}}
            (source/'result.json').write_text(json.dumps(formula))
            folder=root/'jobs/20261022_000001';folder.mkdir()
            request={**request,'formula_source_job':source.name,'selected_model_ids':['B']}
            (folder/'request.json').write_text(json.dumps(request))
            class FakeMC:
                def quit(self):pass
            def fake_solve(mc,label,d,l,n,wire,current,voltage,points,options,geometry):
                calls.append({'label':label,'options':options,'geometry':geometry,'points':points})
                row=copy.deepcopy(template);row['label']=label;row['input_options']=options
                row['design'].update(diameter_mm=d,length_mm=l,turns_per_coil=n,wire_diameter_mm=wire,input_peak_current_A=current,voltage_V=voltage)
                row['geometry_mm'].update(geometry);row['geometry_mm']['Slot_Opening']=2.
                row['readback']['PhaseAdvance']=options['phase_advance_deg']
                row['values'].update({'Shaft Torque':.5025,'System Efficiency':90.,'Line-Line Terminal Voltage (peak)':6.,
                    'Line-Line Terminal Voltage (rms)':4.,'Copper Slot Fill (Slot Area)':.4,'Torque Ripple (MsVw) [%]':10.,
                    'Phase Current (peak)':current/math.sqrt(3),'Phase Current (rms)':current/math.sqrt(6)})
                row['values']['Shaft Torque']=current/40*gain if margin else .5025
                if 'capacity' in label:row['values']['System Efficiency']=80.
                for k in ('Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)','Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)'):row['values'][k]=1.6
                row['voltage_limit_exceeded']=False;row['timings']={'solver_s':1.,'total_s':1.1}
                return row
            with patch.object(verification,'ROOT',root),patch.object(verification.solver,'OUT',folder),\
                 patch.object(verification.solver,'start',return_value=(FakeMC(),.1)),\
                 patch.object(verification.solver,'prepare'),patch.object(verification.solver,'solve',side_effect=fake_solve):
                result=verification.run_verification(request,folder)
            self.assertEqual([c['id'] for c in result['results']],['B'])
            self.assertEqual(len(calls),(4 if gain==.5025 else 8) if margin else 2)
            self.assertTrue(all(c['label'].startswith('B_') for c in calls))
            self.assertTrue(all(c['geometry']['Airgap']==.5 for c in calls))
            self.assertTrue(all(c['points']==120 for c in calls))
            self.assertTrue(all('phase_advance_deg' in c['options'] for c in calls))
            self.assertFalse(result['results'][0]['target_met'])
            c=result['results'][0]
            self.assertTrue(c['condition_coverage']['complete'])
            self.assertEqual(c['worst_efficiency_pct'],90.)
            if margin:
                import csv
                from result_review import review_result
                self.assertEqual(c['worst_capacity_efficiency_pct'],80.)
                nominal=[r for r in c['runs'] if r['verification_role']=='nominal']
                capacity=[r for r in c['runs'] if r['verification_role']=='capacity']
                self.assertTrue(all(r['assessment']['requirement_details']['capacity_torque_Nm']['state']=='passed' for r in nominal))
                self.assertTrue(all(r['assessment']['requirement_details']['efficiency_pct']['state']=='violated' for r in capacity))
                self.assertTrue(all(r['target_torque_Nm']==.55 for r in capacity))
                self.assertEqual(result['verification_estimate']['base_solves'],4)
                self.assertEqual(result['verification_estimate']['max_solves_with_corrections'],12)
                review=review_result(result,folder)['candidates'][0]
                self.assertTrue(all(m['difference'] is None for r in review['runs'] if r['verification_role']=='capacity' for m in r['metrics']))
                with (folder/'motorcad.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
                self.assertTrue(any(r['condition_id'].startswith('capacity_') for r in rows))
                c['runs']=nominal
                review=review_result(result,folder)['candidates'][0]
                self.assertFalse(review['condition_coverage']['complete'])
                self.assertFalse(review['target_met'])
                self.assertTrue(all(next(q for q in r['requirements'] if q['id']=='capacity_torque_Nm')['state']=='unverified' for r in review['runs']))


if __name__=='__main__':unittest.main()
