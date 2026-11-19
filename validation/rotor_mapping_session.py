"""Disposable native mapping session; never runs FEA."""
import argparse
import contextlib
from pathlib import Path
import time
from study_io import write_json


if __name__=='__main__':
    from ansys.motorcad.core import MotorCAD
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();folder=a.output.resolve();folder.mkdir(parents=True,exist_ok=True);mc=None
    try:
        mc=MotorCAD(open_new_instance=True,keep_instance_open=False)
        mc.set_variable('MessageDisplayState',2);mc.load_from_file(str(a.source.resolve()))
        model=folder/'TYPE_MAPPING_REVIEW.mot';mc.save_to_file(str(model));mc.set_visible(True)
        write_json(folder/'session.json',{'status':'ready','BPMRotor':mc.get_variable('BPMRotor'),'source_model':str(model),'new_fea':0})
        started=time.time()
        while time.time()-started<900:
            if (folder/'stop.request').exists():break
            if (folder/'capture.request').exists():
                (folder/'capture.request').unlink()
                selected=mc.get_variable('BPMRotor');mc.save_to_file(str(folder/'selected_type.mot'))
                tree=mc.get_geometry_tree()._to_json();write_json(folder/'selected_geometry.json',tree)
                write_json(folder/'captured.json',{'BPMRotor':selected,'Magnet_Arc_ED':mc.get_variable('Magnet_Arc_[ED]'),'new_fea':0})
            time.sleep(1)
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
