"""Read native Breadloaf geometry on disposable copies. No FEA calls."""
import argparse
import contextlib
from pathlib import Path
import time
import traceback
from study_io import write_json

ROOT=Path(__file__).resolve().parent


def run(source,folder):
    import msvcrt
    from ansys.motorcad.core import MotorCAD
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    mc=None;lock=None;started=time.time();rows=[]
    if (folder/'progress.json').exists():raise ValueError('Fresh probe folder required')
    def progress(state,**extra):write_json(folder/'progress.json',{'status':state,'new_fea':0,'elapsed_s':time.time()-started,**extra})
    try:
        lock=(ROOT/'motorcad_execution.lock').open('a+b')
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        progress('starting')
        mc=MotorCAD(open_new_instance=True,keep_instance_open=False)
        mc.set_variable('MessageDisplayState',2);mc.set_visible(False)
        for reduction in (.2,.4,.6):
            progress('reading_geometry',reduction_mm=reduction)
            mc.load_from_file(str(Path(source).resolve()))
            expected={'BPMRotor':2,'MagnetReduction':reduction,'CircumferentialSegments':1}
            for key,value in expected.items():mc.set_variable(key,value)
            model=folder/('reduction_'+str(reduction)+'.mot')
            mc.save_to_file(str(model.resolve()));mc.load_from_file(str(model.resolve()))
            actual={key:mc.get_variable(key) for key in expected}
            if any(abs(actual[key]-v)>1e-7 for key,v in expected.items()):raise RuntimeError('Breadloaf readback mismatch')
            tree=mc.get_geometry_tree()
            write_json(folder/('geometry_'+str(reduction)+'.json'),tree._to_json())
            magnets=[]
            for region in tree.values():
                if 'magnet' in region.name.lower():
                    magnets.append({'name':region.name,'area_mm2':region.area,'geometry':region._to_json()})
            if not magnets:raise RuntimeError('No magnet regions found in native geometry tree')
            rows.append({'reduction_mm':reduction,'readback':actual,'magnets':magnets})
            write_json(folder/'partial_results.json',rows)
        write_json(folder/'result.json',{'status':'completed','new_fea':0,'rows':rows,
            'corner_geometry_qualified':False,'note':'Native boundaries extracted. Quantitative corner interpretation still requires analysis.'})
        progress('completed')
    except BaseException as exc:
        write_json(folder/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});progress('failed');raise
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        if lock:lock.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.source,a.output)
