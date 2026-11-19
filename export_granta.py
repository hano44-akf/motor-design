"""Export user-supplied Granta names through Motor-CAD, one material per call."""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import shutil
import traceback
import sys
import time
from ansys.motorcad.core import MotorCAD
import psutil
from collect_materials import parse_mdb, summarize

ROOT = Path(__file__).resolve().parent
BASE = Path('C:/Users/jo061/AppData/Roaming/Ansys/v261/MotorCAD/materials')
LIST = Path('C:/Users/jo061/.codex/attachments/dd287d61-37a9-4a69-8b79-ff41705d54b2/pasted-text.txt')

def main():
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / 'granta_runs' / datetime.now().strftime('%Y%m%d_%H%M%S')
    out.mkdir(parents=True, exist_ok=True)
    source = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else BASE / 'Granta_Magnets/Neodymium_magnet.gdb'
    table_path = Path(sys.argv[2]) if len(sys.argv) > 2 else LIST
    raw = table_path.read_bytes()
    rows = [l.split('\t') for l in raw.decode('utf-8-sig').splitlines() if l.strip()]
    if any(len(r) != 54 or r[2] not in ('Magnet', 'Steel') for r in rows):
        raise ValueError('Unexpected pasted table format')
    names = [r[1] for r in rows]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate material names')
    (out / 'supplied_table.tsv').write_bytes(raw)
    report = {'source_database': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'requested_count': len(names), 'requested_names': names, 'results': [],
              'scope': 'User supplied names only; completeness of whole GDB not independently established'}
    if (out / 'report.json').exists():
        previous = json.loads((out / 'report.json').read_text(encoding='utf-8'))
        if previous['source_sha256'] != report['source_sha256'] or previous['requested_names'] != names:
            raise ValueError('Resume source mismatch')
        report['results'] = [r for r in previous['results'] if r.get('status') == 'exported']
        for item in report['results']:
            if hashlib.sha256((out / item['file']).read_bytes()).hexdigest() != item['sha256']:
                raise ValueError('Resume output mismatch')
    def save():
        temp = out / 'report.tmp'
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(out / 'report.json')
    save()
    mc = None
    print('OUTPUT ' + str(out), flush=True)
    try:
        working = out / 'working.mdb'
        shutil.copy2(BASE / 'solids_test.mdb', working)
        mc = MotorCAD(open_new_instance=True, keep_instance_open=False)
        # Use the IPv4 listener of this exact new instance to avoid localhost resolution delays.
        listeners = [c.laddr.port for c in psutil.net_connections('tcp')
                     if c.pid == mc.connection.pid and c.status == 'LISTEN' and c.laddr.ip == '0.0.0.0']
        if len(listeners) == 1:
            mc.connection._url = f'http://127.0.0.1:{listeners[0]}'
        print('Connected ' + mc.connection._get_url(), flush=True)
        mc.set_visible(False)
        mc.set_variable('MessageDisplayState', 2)
        mc.select_material_database(str(working), False)
        report['motorcad_version'] = mc.connection.program_version
        for index, name in enumerate(names):
            if any(r['name'] == name and r['status'] == 'exported' for r in report['results']):
                continue
            started = time.perf_counter()
            item = {'name': name, 'index': index, 'status': 'started'}
            report['results'].append(item)
            save()
            try:
                mc.import_solid_material(str(source), name)
                path = out / f'{index:04d}.mdb'
                mc.export_solid_material(str(path), name)
                data = path.read_bytes()
                encoding, sections, _ = parse_mdb(data)
                matches = [s for s in sections if s['name'] == name]
                if len(matches) != 1:
                    raise ValueError('Exported material name mismatch')
                values, arrays, curves, warnings = summarize(matches[0])
                if values.get('Solid Type') != rows[index][2]:
                    raise ValueError('Exported material type mismatch')
                if any(not c['indices_match'] for c in curves):
                    raise ValueError('Mismatched curve indices')
                item.update(status='exported', file=path.name, sha256=hashlib.sha256(data).hexdigest(),
                            curves=curves, warnings=warnings,
                            temperatures=sorted(set(float(p['raw_value']) for p in arrays.get('Temperature', []))))
                # Keep the isolated temporary database small; original user DB is never edited.
                mc.delete_solid_material(name)
                save()
                print(f'{index+1}/{len(names)} {name}: exported ({time.perf_counter()-started:.2f}s)', flush=True)
            except Exception:
                item['status'] = 'failed'
                item['error'] = traceback.format_exc()
                report['status'] = 'stopped_on_error'
                save()
                print(item['error'], flush=True)
                break
        else:
            report['status'] = 'all_requested_exported'
    except Exception:
        report['status'] = 'failed'
        report['error'] = traceback.format_exc()
        print(report['error'], flush=True)
    finally:
        if mc:
            try:
                mc.quit()
            except Exception as exc:
                report['cleanup_error'] = str(exc)
        save()
        print('FINAL ' + report.get('status', 'unknown'), flush=True)

if __name__ == '__main__':
    main()
