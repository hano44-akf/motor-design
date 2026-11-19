"""Isolated Motor-CAD material import/export probe; never edits the source DB."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import traceback
from ansys.motorcad.core import MotorCAD

ROOT = Path(__file__).resolve().parent
SOURCE = Path('C:/Users/jo061/AppData/Roaming/Ansys/v261/MotorCAD/materials')

def main():
    out = ROOT / 'material_runs' / datetime.now().strftime('%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=False)
    seed = SOURCE / 'solids_test.mdb'
    database = SOURCE / 'Granta_Magnets/Neodymium_magnet.gdb'
    name = 'HPMG | N35SH'
    report = {'started_utc': datetime.now(timezone.utc).isoformat(),
              'source': str(database), 'material_name': name, 'steps': []}
    mc = None
    try:
        for path in (seed, database):
            if not path.is_file():
                raise FileNotFoundError(path)
        report['source_sha256'] = hashlib.sha256(database.read_bytes()).hexdigest()
        working = out / 'working.mdb'
        shutil.copy2(seed, working)
        print('Starting isolated Motor-CAD instance', flush=True)
        mc = MotorCAD(open_new_instance=True, keep_instance_open=False)
        mc.set_visible(False)
        report['steps'].append('new_instance_connected')
        print('Selecting copied database', flush=True)
        mc.select_material_database(str(working), False)
        report['steps'].append('working_database_selected')
        print('Importing ' + name, flush=True)
        mc.import_solid_material(str(database), name)
        report['steps'].append('material_imported')
        target = out / 'N35SH.mdb'
        mc.export_solid_material(str(target), name)
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError('Export file missing or empty')
        report['steps'].append('material_exported')
        report['output'] = str(target)
        report['output_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
        report['status'] = 'exported_not_curve_validated'
        print('EXPORTED: ' + str(target), flush=True)
    except Exception:
        report['status'] = 'failed'
        report['error'] = traceback.format_exc()
        print(report['error'], flush=True)
    finally:
        if mc is not None:
            try:
                mc.quit()
            except Exception as exc:
                report['cleanup_error'] = str(exc)
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('REPORT: ' + str(out / 'report.json'), flush=True)

if __name__ == '__main__':
    main()
