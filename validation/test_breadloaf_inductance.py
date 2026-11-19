import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from breadloaf_inductance import SETTINGS,configure,launch

SNAPSHOT=Path(__file__).resolve().parent.parent/'outputs/breadloaf_fine_verification_20261105/breadloaf_search_13_614_1_snapshot.json'


class FakeMC:
    def __init__(self):
        self.values=json.loads(SNAPSHOT.read_text(encoding='utf-8'))['expected_native'];self.values['MagPhases']=3
        self.mutations=[]
    def get_variable(self,name):return self.values[name]
    def set_variable(self,name,value):self.values[name]=value;self.mutations.append(name)


class InductanceExperimentTests(unittest.TestCase):
    def test_configure_preserves_bias_and_disables_unrelated_calculations(self):
        mc=FakeMC();current=mc.values['PeakCurrent']
        actual=configure(mc,{'source_snapshot':str(SNAPSHOT),'settings':copy.deepcopy(SETTINGS)})
        self.assertEqual(mc.values['PeakCurrent'],current)
        self.assertFalse(actual['TorqueCalculation']);self.assertFalse(actual['BackEMFCalculation'])
        self.assertTrue(actual['InductanceCalc']);self.assertEqual(actual['InductanceNumberCycles'],1)
        self.assertEqual(actual['InductanceSolver_BPM'],0)

    def test_wrong_input_is_rejected_before_any_setting_mutation(self):
        mc=FakeMC();mc.values['PeakCurrent']-=1
        with self.assertRaisesRegex(ValueError,'Verified input mismatch'):
            configure(mc,{'source_snapshot':str(SNAPSHOT),'settings':SETTINGS})
        self.assertEqual(mc.mutations,[])

    def test_native_launch_requires_matching_settings_probe(self):
        with tempfile.TemporaryDirectory() as tmp,patch('breadloaf_inductance.subprocess.Popen') as popen:
            folder=Path(tmp);(folder/'plan.json').write_text(json.dumps({'settings':SETTINGS}))
            with self.assertRaisesRegex(ValueError,'settings probe required'):launch(folder)
            (folder/'capability_probe.json').write_text(json.dumps({'status':'settings_supported','readback':{}}))
            with self.assertRaisesRegex(ValueError,'settings probe required'):launch(folder)
            popen.assert_not_called()


if __name__=='__main__':unittest.main()
