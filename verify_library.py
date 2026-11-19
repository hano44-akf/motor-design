"""Independent byte, line and tabular coverage checks for a collected library."""
import csv
import json
import hashlib
import sys
from pathlib import Path

def verify(root):
    bundle = json.loads((root / 'materials_raw.json').read_text(encoding='utf-8'))
    checked_lines = 0
    for db in bundle['databases']:
        source = root / db['sources'][0]['archive_path']
        data = source.read_bytes()
        assert hashlib.sha256(data).hexdigest() == db['sha256']
        if db['format'] != '.mdb':
            continue
        text = data.decode(db['encoding'])
        source_fields = [line for line in text.splitlines() if '=' in line]
        parsed_fields = [entry['key'] + '=' + entry['value']
                         for section in db['sections'] for entry in section['entries']]
        assert source_fields == parsed_fields, source
        source_headers = [line.strip()[1:-1] for line in text.splitlines()
                          if line.strip().startswith('[') and line.strip().endswith(']')]
        assert source_headers == [s['name'] for s in db['sections']], source
        checked_lines += len(source_fields)
    expected = [(r['id'], field, str(p['index']), p['raw_value'])
                for r in bundle['materials'] for field, points in r['indexed_arrays'].items() for p in points]
    with (root / 'indexed_values.csv').open(encoding='utf-8-sig', newline='') as stream:
        actual = [(r['material_id'], r['field'], r['index'], r['raw_value']) for r in csv.DictReader(stream)]
    assert expected == actual
    warnings = {}
    for record in bundle['materials']:
        for warning in record['warnings']:
            kind = warning.split(':')[0]
            warnings[kind] = warnings.get(kind, 0) + 1
    report = {'status': 'passed', 'unique_archived_files_checked': len(bundle['databases']),
              'source_field_lines_checked': checked_lines, 'indexed_csv_values_checked': len(actual),
              'warning_counts': warnings, 'physical_accuracy_validation': 'not_performed'}
    (root / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    verify(Path(sys.argv[1]))
