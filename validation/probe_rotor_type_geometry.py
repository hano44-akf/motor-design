"""SDK geometry evidence only: never infer type names from menu order."""
import argparse
import contextlib
from pathlib import Path
import time
import traceback
from study_io import write_json

if __name__=='__main__':
    import msvcrt
    from ansys.motorcad.core import MotorCAD
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True);mc=None;rows=[]
    root=Path(__file__).resolve().parent;lock=(root/'motorcad_execution.lock').open('a+b')
    try:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        mc=MotorCAD(open_new_instance=True,keep_instance_open=False);mc.set_variable('MessageDisplayState',2);mc.set_visible(False)
        for code in range(16):
            write_json(out/'progress.json',{'status':'probing','active_code':code,'completed':len(rows),'new_fea':0})
            try:
                mc.load_from_file(str(a.source.resolve()));mc.set_variable('BPMRotor',code)
                value=mc.get_variable('BPMRotor')
                mc.save_to_file(str(out/('type_'+str(code)+'.mot')))
                mc.load_from_file(str(out/('type_'+str(code)+'.mot')))
                mc.reset_adaptive_geometry()
                tree=mc.get_geometry_tree()._to_json();write_json(out/('type_'+str(code)+'.json'),tree)
                magnets=[v for v in tree['regions'].values() if v.get('region_type')=='Magnet']
                rows.append({'code':code,'readback':value,'magnet_regions':[{'name':m['name'],'area':m['area'],
                    'entities':[e['type'] for e in m['entities']],'centroid':m['centroid']} for m in magnets],
                    'name_verified':False})
            except Exception as exc:rows.append({'code':code,'error':str(exc)})
            write_json(out/'results.json',rows)
        write_json(out/'progress.json',{'status':'completed','completed':len(rows),'new_fea':0})
    except BaseException as exc:write_json(out/'error.json',{'error':str(exc),'traceback':traceback.format_exc()});raise
    finally:
        if mc:
            with contextlib.suppress(Exception):mc.quit()
        lock.close()
