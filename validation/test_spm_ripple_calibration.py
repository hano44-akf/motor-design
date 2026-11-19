import unittest
import numpy as np
from spm_ripple_calibration import fit,transform,apply


class CalibrationTests(unittest.TestCase):
    def test_component_fit_recovers_known_wave_without_percent_targets(self):
        theta=np.arange(120)*2*np.pi/120;rows=[]
        parameters=np.array([.7,.9,.5,.02,.003])
        for i in range(6):
            c=.1*(1+i/5)*np.sin(12*theta+.1*i)
            m=.6+.15*np.cos(12*theta-.15*i)
            r=.03*np.cos(24*theta+.2*i)
            proxy={'cogging_Nm':c.tolist(),'mutual_Nm':m.tolist(),'reluctance_Nm':r.tolist(),
                'torque_Nm':(c+m+r).tolist(),'ripple_pct':100,'qualified':False,'rotor_id':'surface_radial'}
            rows.append({'id':str(i),'rotor_id':'surface_radial','proxy':proxy,'actual_waveform_Nm':transform(proxy,parameters).tolist()})
        calibration=fit(rows)
        self.assertFalse(calibration['qualified']);self.assertEqual(calibration['training_ids'],list(map(str,range(6))))
        output=apply(rows[0]['proxy'],calibration)
        self.assertFalse(output['qualified']);self.assertEqual(output['raw_ripple_pct'],100)
        self.assertLess(np.sqrt(np.mean((np.array(output['torque_Nm'])-rows[0]['actual_waveform_Nm'])**2)),.001)

    def test_too_few_development_records_are_rejected(self):
        with self.assertRaises(ValueError):fit([])

    def test_unseen_shape_blocked_except_explicit_experiment(self):
        proxy={'rotor_id':'surface_flat','cogging_Nm':[0]*120,'mutual_Nm':[1]*120,
               'reluctance_Nm':[0]*120,'ripple_pct':0}
        calibration={'training_shapes':['surface_radial'],'training_ids':['development'],
                     'parameters':[1,1,1,0,0]}
        with self.assertRaises(ValueError):apply(proxy,calibration)
        experimental=apply(proxy,calibration,allow_unseen_shape=True)
        self.assertEqual(experimental['calibration_domain'],'unseen_shape_experimental_transfer')
        self.assertFalse(experimental['optimization_eligible'])
        self.assertFalse(experimental['qualified'])


if __name__=='__main__':unittest.main()
