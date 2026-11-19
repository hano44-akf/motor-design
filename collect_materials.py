"""Archive Motor-CAD databases and collect lossless MDB records. Standard library only."""
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter
import csv
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent
SOURCES = {
    'installation': Path('C:/Program Files/ANSYS Inc/v261/motorcad/Motor-CAD Data/materials'),
    'user': Path('C:/Users/jo061/AppData/Roaming/Ansys/v261/MotorCAD/materials'),
}

def digest(data):
    return hashlib.sha256(data).hexdigest()

def parse_mdb(data):
    for encoding in ('utf-8-sig', 'cp1252', 'cp949'):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError('Unsupported encoding; original bytes retained')
    sections, current, preamble = [], None, []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            current = {'name': stripped[1:-1], 'raw_header': line, 'line': number, 'entries': [], 'other_lines': []}
            sections.append(current)
        elif current is None:
            preamble.append({'line': number, 'text': line})
        elif '=' in line:
            key, value = line.split('=', 1)
            current['entries'].append({'key': key, 'value': value})
        else:
            current['other_lines'].append({'line': number, 'text': line})
    return encoding, sections, preamble

def summarize(section):
    values = {}
    warnings = []
    arrays = {}
    for entry in section['entries']:
        key, value = entry['key'], entry['value']
        if key in values:
            warnings.append('duplicate_key:' + key)
        values[key] = value
        match = re.fullmatch(r'(.+)\[(\d+)\]', key)
        if match:
            arrays.setdefault(match[1], []).append({'index': int(match[2]), 'raw_value': value})
    for prefix, points in arrays.items():
        points.sort(key=lambda p: p['index'])
        indices = [p['index'] for p in points]
        if indices != list(range(len(indices))):
            warnings.append('non_contiguous_or_duplicate_indices:' + prefix)
    curves = []
    for kind, keys in [('steel_bh', ('BValue', 'HValue')),
                       ('magnet_bh', ('Temperature', 'BValue_Magnet', 'HValue_Magnet')),
                       ('steel_loss', ('Frequency', 'FluxDensity', 'LossDensity'))]:
        if not any(k in arrays for k in keys):
            continue
        indices = [{p['index'] for p in arrays.get(k, [])} for k in keys]
        complete = all(i == indices[0] for i in indices)
        if not complete:
            warnings.append('mismatched_curve_indices:' + kind)
        curves.append({'kind': kind, 'fields': list(keys), 'point_count': len(set.intersection(*indices)),
                       'indices_match': complete, 'units_status': 'raw_source_fields_not_normalized'})
    return values, arrays, curves, warnings

def write_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def collect():
    out = ROOT / 'material_library' / datetime.now().strftime('%Y%m%d_%H%M%S')
    archive = out / 'raw'
    archive.mkdir(parents=True, exist_ok=False)
    inventory, databases, records = [], {}, {}
    paths = [(tag, base, p) for tag, base in SOURCES.items() if base.is_dir()
             for p in sorted(base.rglob('*')) if p.is_file() and p.suffix.lower() in ('.mdb', '.gdb')]
    # Include only verified API export artifacts, not temporary working database copies.
    for report_path in sorted((ROOT / 'material_runs').glob('*/report.json')):
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if report.get('status') == 'exported_not_curve_validated':
            p = Path(report['output'])
            if p.is_file():
                if digest(p.read_bytes()) != report['output_sha256']:
                    raise ValueError('API export hash mismatch: ' + str(p))
                paths.append(('verified_api_export', p.parent, p))
    granta_provenance = []
    for report_path in sorted((ROOT / 'granta_runs').glob('*/report.json')):
        report = json.loads(report_path.read_text(encoding='utf-8'))
        for item in report.get('results', []):
            if item.get('status') != 'exported':
                continue
            p = report_path.parent / item['file']
            if digest(p.read_bytes()) != item['sha256']:
                raise ValueError('Granta export hash mismatch: ' + str(p))
            paths.append(('granta_official_api_export', p.parent, p))
            granta_provenance.append({'material_name': item['name'], 'export_sha256': item['sha256'],
                'source_database': report['source_database'], 'source_sha256': report['source_sha256'],
                'report_path': str(report_path)})
    for tag, base, path in paths:
        data = path.read_bytes()
        sha = digest(data)
        raw_path = archive / (sha + path.suffix.lower())
        if not raw_path.exists():
            raw_path.write_bytes(data)
        if digest(raw_path.read_bytes()) != sha:
            raise ValueError('Archive verification failed')
        occurrence = {'source_group': tag, 'source_path': str(path), 'relative_path': str(path.relative_to(base)),
                      'sha256': sha, 'bytes': len(data), 'archive_path': str(raw_path.relative_to(out))}
        inventory.append(occurrence)
        if sha in databases:
            databases[sha]['sources'].append(occurrence)
            continue
        db = {'sha256': sha, 'sources': [occurrence], 'format': path.suffix.lower(), 'material_ids': []}
        databases[sha] = db
        if path.suffix.lower() == '.gdb':
            db['status'] = 'encrypted_not_enumerated_or_bulk_exported'
            continue
        try:
            encoding, sections, preamble = parse_mdb(data)
            db.update(encoding=encoding, sections=sections, preamble=preamble, status='parsed_raw_not_physics_validated')
            for section in sections:
                values, arrays, curves, warnings = summarize(section)
                if section['name'] == 'Header' and not any(k in values for k in ('Type', 'Solid Type')):
                    continue
                canonical = {'name': section['name'], 'entries': section['entries'],
                             'other_text': [x['text'] for x in section['other_lines']]}
                record_id = digest(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode('utf-8'))
                if record_id not in records:
                    records[record_id] = {'id': record_id, 'name': section['name'],
                        'type': values.get('Solid Type', values.get('Type', 'unknown')),
                        'raw_entries': section['entries'], 'other_text': canonical['other_text'],
                        'indexed_arrays': arrays, 'curves': curves, 'warnings': warnings, 'origins': [],
                        'validation_status': 'raw_structural_only'}
                records[record_id]['origins'].append({'database_sha256': sha, 'section_line': section['line']})
                db['material_ids'].append(record_id)
        except Exception as exc:
            db['status'] = 'parse_failed_original_archived'
            db['error'] = str(exc)
    names = Counter(r['name'] for r in records.values())
    catalog = []
    points = []
    fields_rows = []
    for r in records.values():
        if names[r['name']] > 1:
            r['warnings'].append('same_name_multiple_content_versions')
        catalog.append({'id': r['id'], 'name': r['name'], 'type': r['type'],
                        'raw_field_count': len(r['raw_entries']), 'origin_count': len(r['origins']),
                        'curves': ';'.join(c['kind'] for c in r['curves']),
                        'warnings': ';'.join(r['warnings']), 'validation_status': r['validation_status']})
        for order, entry in enumerate(r['raw_entries']):
            fields_rows.append({'material_id': r['id'], 'field_order': order, **entry})
        for field, array in r['indexed_arrays'].items():
            for point in array:
                points.append({'material_id': r['id'], 'field': field, **point})
    summary = {'source_file_occurrences': len(inventory), 'unique_database_files': len(databases),
               'unique_mdb_files': sum(d['format'] == '.mdb' for d in databases.values()),
               'unique_encrypted_gdb_files': sum(d['format'] == '.gdb' for d in databases.values()),
               'unique_material_records': len(records), 'types': dict(Counter(r['type'] for r in records.values())),
               'indexed_values': len(points), 'raw_fields': len(fields_rows),
               'records_with_warnings': sum(bool(r['warnings']) for r in records.values()),
               'parse_failures': sum(d['status'] == 'parse_failed_original_archived' for d in databases.values())}
    bundle = {'schema_version': '0.1', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'scope': {tag: str(p) for tag, p in SOURCES.items()},
              'summary': summary, 'inventory': inventory, 'databases': list(databases.values()),
              'materials': list(records.values()), 'granta_provenance': granta_provenance,
              'limitations': ['GDB names/content not bulk enumerated. Only previous verified API exports included.',
                              'No unit normalization, fitting, missing-value substitution, or physics validation.',
                              'Same-name differing records retained; catalog is not a preferred-material selection.']}
    target = out / 'materials_raw.json'
    target.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    loaded = json.loads(target.read_text(encoding='utf-8'))
    if loaded != bundle:
        raise ValueError('JSON roundtrip failed')
    write_csv(out / 'catalog.csv', catalog, list(catalog[0]))
    write_csv(out / 'raw_fields.csv', fields_rows, ['material_id', 'field_order', 'key', 'value'])
    write_csv(out / 'indexed_values.csv', points, ['material_id', 'field', 'index', 'raw_value'])
    # Validate every CSV raw value, including duplicate fields and blank values.
    with (out / 'raw_fields.csv').open(encoding='utf-8-sig', newline='') as stream:
        restored = list(csv.DictReader(stream))
    if len(restored) != len(fields_rows) or any(a['value'] != b['value'] or a['key'] != b['key']
                                             for a, b in zip(restored, fields_rows)):
        raise ValueError('CSV field roundtrip failed')
    summary['json_and_raw_field_csv_roundtrip'] = 'passed'
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return out

if __name__ == '__main__':
    collect()
