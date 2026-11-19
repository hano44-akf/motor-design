import json
from pathlib import Path
import unittest
from unittest.mock import Mock,patch
from magnet_boundary_check import check_region
from run_spm_ripple_recovery import stop_owned

ROOT=Path(__file__).resolve().parent.parent


def polygon(points):
    return {'entities':[{'type':'line','start':dict(zip(('x','y'),a)),'end':dict(zip(('x','y'),b))} for a,b in zip(points,points[1:]+points[:1])]}


class BoundaryTests(unittest.TestCase):
    def test_closed_rectangle_and_crossed_loop(self):
        self.assertTrue(check_region(polygon([(0,0),(2,0),(2,1),(0,1)]))['passed'])
        self.assertFalse(check_region(polygon([(0,0),(2,1),(0,1),(2,0)]))['passed'])

    def test_open_boundary_and_nan_are_rejected(self):
        r=polygon([(0,0),(2,0),(2,1),(0,1)]);r['entities'][0]['end']['x']=3
        self.assertFalse(check_region(r)['passed'])
        r=polygon([(0,0),(2,0),(2,1),(0,1)]);r['entities'][0]['start']['x']=float('nan')
        self.assertFalse(check_region(r)['passed'])

    def test_real_hanging_breadloaf_rejected_and_flat_passes(self):
        p=ROOT/'outputs/spm_ripple_validation_v2_20261103_140824'
        if not p.exists():self.skipTest('Saved data missing')
        bad=json.loads((p/'surface_breadloaf_08_snapshot.json').read_text(encoding='utf-8'))
        good=json.loads((p/'surface_flat_16_snapshot.json').read_text(encoding='utf-8'))
        self.assertFalse(check_region(bad['magnet_region'])['passed'])
        self.assertTrue(check_region(good['magnet_region'])['passed'])

    def test_timeout_targets_only_owned_native_descendants(self):
        native=Mock();native.name.return_value='MotorCAD.exe'
        other=Mock();other.name.return_value='other.exe'
        owner=Mock();owner.children.return_value=[native,other]
        worker=Mock();worker.pid=123;worker.poll.return_value=0
        with patch('run_spm_ripple_recovery.psutil.Process',return_value=owner) as lookup:
            stop_owned(worker)
            lookup.assert_called_once_with(123)
        native.terminate.assert_called_once();other.terminate.assert_not_called();worker.terminate.assert_not_called()


if __name__=='__main__':unittest.main()
