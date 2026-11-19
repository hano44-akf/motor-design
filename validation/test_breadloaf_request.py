import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from breadloaf_request import adapt
from review_breadloaf_verification import review

ROOT=Path(__file__).resolve().parent.parent


def snapshot():
    return {'core':['50PN470'],'grades':[48],'suffix':['UH'],'spm':{'shape':'Breadloaf','magnetisation':'Radial'},
            'temp':20,'units':'mm','control':'FOC · Id = 0','modulation':'SVPWM','priority':'균형형',
            'eta':100,'mechanical':0,'margin':10,'ops':[{'torque':.5,'rpm':3500,'vmin':9,'vrated':12,'vmax':16,'eff':88,'density':5,'imax':25}],
            'geometry':{},'modes':{}}


class InputContractTests(unittest.TestCase):
    def test_shaft_margin_current_density_and_deferred_constraints(self):
        c=adapt(snapshot())
        self.assertTrue(c['can_search'],c['errors'])
        self.assertAlmostEqual(c['requested_shaft_torque_Nm'],.55)
        self.assertEqual(c['target_basis'],'shaft')
        self.assertAlmostEqual(c['max_line_peak_A'],math.sqrt(6)*5*math.pi*1.8**2/4)
        self.assertEqual(c['requirements']['efficiency_min_pct'],88)
        self.assertFalse(c['full_requirement_optimization'])
        self.assertGreater(len(c['deferred']),2)

    def test_unsupported_conditions_not_silently_ignored(self):
        for field,value in [('temp',100),('connection','star'),('mechanical',5),('control','FOC · MTPA')]:
            s=snapshot();s[field]=value;self.assertFalse(adapt(s)['can_search'])
        s=snapshot();s['ops'].append(s['ops'][0]);self.assertFalse(adapt(s)['can_search'])
        s=snapshot();s['modes']['od']='range';s['ranges']={'od':{'min':55,'max':100}}
        self.assertFalse(adapt(s)['can_search'])

    def test_units_and_switching_limit(self):
        s=snapshot();s.update(units='cm',geometry={'od':8.5},modes={'od':'fixed'})
        self.assertTrue(adapt(s)['can_search'])
        s['switchingKHz']=1
        self.assertFalse(adapt(s)['can_search'])
        s['switchingKHz']=float('nan');self.assertFalse(adapt(s)['can_search'])

    def test_saved_fea_review_does_not_confuse_shaft_and_electromagnetic_torque(self):
        source=ROOT/'outputs/breadloaf_current_feedback_20261104'
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            for f in source.glob('*_snapshot.json'): (p/f.name).write_bytes(f.read_bytes())
            for f in source.glob('*_proxy.json'): (p/f.name).write_bytes(f.read_bytes())
            (p/'result.json').write_bytes((source/'result.json').read_bytes())
            plan=json.loads((source/'plan.json').read_text());plan.pop('feedback')
            s=snapshot();s['margin']=0;plan['request_contract']=adapt(s)
            (p/'plan.json').write_text(json.dumps(plan))
            r=review(p)['cases'][0]
            self.assertEqual(r['requirements']['shaft_torque']['state'],'violated')
            self.assertEqual(r['requirements']['additional_voltages']['state'],'unverified')
            self.assertEqual(r['requirements']['pwm_current_ripple']['state'],'unverified')
            self.assertEqual(r['current_feedback_torque_metric'],'Shaft Torque')
            self.assertAlmostEqual(r['current_feedback_observations'][-1]['torque_Nm'],.48245)


if __name__=='__main__':unittest.main()
