"""Lossless raw-field preservation plus explicit magnet BH tables (no fitting)."""
import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

def convert(source):
    data = source.read_bytes()
    text = data.decode('utf-8-sig')
    fields = {}
    name = None
    for line in text.splitlines():
        if line.startswith('[') and line.endswith(']'):
            if name is not None:
                raise ValueError('Expected exactly one material section')
            name = line[1:-1]
        elif '=' in line:
            key, value = line.split('=', 1)
            if key in fields:
                raise ValueError('Duplicate field: ' + key)
            fields[key] = value
        elif line.strip():
            raise ValueError('Unrecognized line: ' + line)
    if fields.get('Solid Type') != 'Magnet':
        raise ValueError('Only single-material magnet MDB supported')
    arrays = {}
    for prefix in ('Temperature', 'BValue_Magnet', 'HValue_Magnet'):
        arrays[prefix] = {int(m.group(1)): float(value)
                          for key, value in fields.items()
                          if (m := re.fullmatch(re.escape(prefix) + r'\[(\d+)\]', key))}
    indices = set(arrays['Temperature'])
    if not indices or any(set(a) != indices for a in arrays.values()):
        raise ValueError('Missing or mismatched BH point indices')
    rows = [{'index': i, 'temperature_degC': arrays['Temperature'][i],
             'B_T': arrays['BValue_Magnet'][i], 'H_A_per_m': arrays['HValue_Magnet'][i]}
            for i in sorted(indices)]
    result = {'schema_version': '0.1', 'name': name,
              'source_file': source.name, 'source_sha256': hashlib.sha256(data).hexdigest(),
              'status': 'exported_structurally_checked_not_independently_validated',
              'raw_fields': fields, 'bh_points': rows,
              'warnings': ['No extrapolation or fitting performed.',
                           'Derived scalar parameters retain Motor-CAD reference temperature.',
                           'Source GDB curve fidelity has not been independently checked.']}
    target = source.with_suffix('.json')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    with source.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    loaded = json.loads(target.read_text(encoding='utf-8'))
    assert loaded['raw_fields'] == fields
    assert loaded['bh_points'] == rows
    with source.with_suffix('.csv').open(encoding='utf-8-sig', newline='') as stream:
        csv_rows = list(csv.DictReader(stream))
    assert len(csv_rows) == len(rows)
    for original, exported in zip(rows, csv_rows):
        assert all(float(exported[k]) == v for k, v in original.items())
    counts = Counter(row['temperature_degC'] for row in rows)
    print(json.dumps({'material': name, 'point_counts_by_temperature_degC': dict(counts),
                      'json_csv_roundtrip': 'passed'}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    convert(Path(sys.argv[1]))
