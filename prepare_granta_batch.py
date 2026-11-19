from pathlib import Path
from collections import Counter, defaultdict
import json
import re
from datetime import datetime

ROOT = Path(__file__).resolve().parent
ATTACHMENT = Path('C:/Users/jo061/.codex/attachments/5616848f-abc9-4e83-adba-1ee0b7d883b4/pasted-text.txt')

def prepare():
    raw = ATTACHMENT.read_bytes()
    rows = [line.split('\t') for line in raw.decode('utf-8-sig').splitlines() if line.strip()]
    groups = defaultdict(list)
    for row in rows:
        if len(row) != 54 or row[2] not in ('Magnet', 'Steel'):
            raise ValueError('Unexpected row format')
        matches = re.findall(r'from "([^"]+\.gdb)"', row[-1])
        if len(matches) != 1:
            raise ValueError('Missing or ambiguous source: ' + row[1])
        source = Path(matches[0]).resolve()
        allowed = Path('C:/Users/jo061/AppData/Roaming/Ansys/v261/MotorCAD/materials').resolve()
        if not source.is_relative_to(allowed) or not source.is_file():
            raise ValueError('Source is outside materials or missing: ' + str(source))
        groups[str(source)].append(row)
    batch = ROOT / 'granta_batches' / datetime.now().strftime('%Y%m%d_%H%M%S')
    batch.mkdir(parents=True)
    (batch / 'supplied_table.tsv').write_bytes(raw)
    plan = []
    for index, (source, items) in enumerate(groups.items()):
        if len(set(r[1] for r in items)) != len(items):
            raise ValueError('Duplicate names in source')
        table = batch / f'{index:02d}.tsv'
        table.write_text('\n'.join('\t'.join(r) for r in items), encoding='utf-8')
        plan.append({'source': source, 'table': str(table), 'count': len(items),
                     'output': str(ROOT / 'granta_runs' / (batch.name + '_' + str(index)))})
    (batch / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'batch': str(batch), 'total': len(rows), 'groups': plan}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    prepare()
