"""Auditable SI projection of archived MDB fields; originals are never changed."""
from pathlib import Path
from decimal import Decimal, localcontext, InvalidOperation
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'material_library/20261019_161745'
OUT = ROOT / 'material_library/normalized_20261020'
DOC = 'https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/solids_database_file_format.html'
# Explicit documented field names only. No fuzzy unit inference.
RULES = {}
def rule(keys, source_unit, si_unit, factor='1', offset='0'):
    for key in keys.split('|'):
        RULES[key] = dict(source_unit=source_unit, si_unit=si_unit,
                         factor=factor, offset=offset, evidence=DOC,
                         evidence_version='2025 R2; source export 2026.1.2.1; version compatibility not runtime certified')

rule('Thermal Conductivity', 'W/(m degC)', 'W/(m K)')
rule('Specific Heat', 'J/(kg degC)', 'J/(kg K)')
rule('Density', 'kg/m3', 'kg/m3')
rule('ElectricalResistivity', 'ohm m', 'ohm m')
rule('TempCoefElectricalResistivity', '1/degC', '1/K')
rule('MagnetRefTemp|ValidMagnetTemperature_Min|ValidMagnetTemperature_Max|Temperature', 'degC', 'K', offset='273.15')
rule('MagnetBrValue|BKneeDefined|BValue|BValue_Magnet|FluxDensity', 'T', 'T')
rule('MagnetHcJValue|HValue|HValue_Magnet', 'A/m', 'A/m')
rule('MagneturValue|PoissonsRatio', '1', '1')
rule('MagnetTempCoefBr|MagnetTempCoefHcJ', '%/degC', '1/K', factor='0.01')
rule('YieldStress|YoungsCoefficient', 'MPa', 'Pa', factor='1000000')
rule('LaminationThickness', 'mm', 'm', factor='0.001')
rule('Frequency', 'Hz', 'Hz')
rule('LossDensity', 'W/kg', 'W/kg')
TEXT = {'Type', 'Solid Type', 'Notes', 'SteelLossNotes'}
SELECTORS = {'UrCalculationMethod','KneePointMethod','kKey_KneePointMethod','BHExtrapolationEnabled','TempCoeffMethod'}
CURVES = {'magnet_bh': ('Temperature','BValue_Magnet','HValue_Magnet'),
          'steel_bh': ('BValue','HValue'), 'steel_loss': ('Frequency','FluxDensity','LossDensity')}
POSITIVE = {'Thermal Conductivity','Specific Heat','Density','ElectricalResistivity',
            'MagnetBrValue','MagnetHcJValue','MagneturValue','YieldStress','YoungsCoefficient','LaminationThickness'}

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def si(raw, spec):
    with localcontext() as ctx:
        ctx.prec = max(80, len(raw) + 40)
        x = Decimal(raw.strip())
        if not x.is_finite():
            raise ValueError('nonfinite')
        y = x * Decimal(spec['factor']) + Decimal(spec['offset'])
        assert (y-Decimal(spec['offset']))/Decimal(spec['factor']) == x
        return str(y), x

def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def build():
    OUT.mkdir(exist_ok=True)
    payload = json.loads((SOURCE/'materials_raw.json').read_text(encoding='utf-8'))
    staging = OUT/'materials_si.building.sqlite'
    if staging.exists():
        raise FileExistsError(staging)
    con = sqlite3.connect(staging)
    con.executescript('''
    CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE materials(id TEXT PRIMARY KEY, name TEXT, type TEXT, origins_json TEXT, source_warnings_json TEXT);
    CREATE TABLE fields(material_id TEXT REFERENCES materials(id), ordinal INTEGER, raw_key TEXT, base_key TEXT,
      array_index INTEGER, raw_value TEXT, si_value_decimal TEXT, si_unit TEXT, status TEXT, quality TEXT,
      PRIMARY KEY(material_id, ordinal));
    CREATE TABLE unit_rules(base_key TEXT PRIMARY KEY, source_unit TEXT, si_unit TEXT, factor_decimal TEXT, offset_decimal TEXT, evidence TEXT);
    CREATE TABLE curves(material_id TEXT, kind TEXT, point_count INTEGER, status TEXT, detail_json TEXT);
    CREATE TABLE issues(material_id TEXT, raw_key TEXT, code TEXT, detail TEXT);
    CREATE VIEW usable_si_fields AS SELECT * FROM fields WHERE status='normalized' AND quality='unvalidated'
      AND material_id NOT IN (SELECT material_id FROM issues WHERE code IN ('embedded_assignment','duplicate_key','curve_structure_requires_review'));
    ''')
    metadata = {'schema_version':'1.0', 'created_utc':datetime.now(timezone.utc).isoformat(),
                'source_json_sha256':sha(SOURCE/'materials_raw.json'), 'physical_accuracy':'not_validated',
                'representative_materials':'not_selected_user_decision_pending',
                'numeric_storage':'exact decimal text; convert explicitly for numerical solvers',
                'evidence_version':'2025 R2 official file format; 2026.1.2.1 export compatibility requires review',
                'zero_policy':'raw zeros preserved; selected nonpositive physical scalar values flagged',
                'reference_temperature':'not assumed; MagnetRefTemp only applies to documented magnet quantities'}
    con.executemany('INSERT INTO metadata VALUES (?,?)', metadata.items())
    con.executemany('INSERT INTO unit_rules VALUES (?,?,?,?,?,?)',
                    [(k,v['source_unit'],v['si_unit'],v['factor'],v['offset'],v['evidence']) for k,v in RULES.items()])
    statuses=Counter(); field_audit={}; issues=Counter(); converted=0
    for m in payload['materials']:
        mid=m['id']; entries=m['raw_entries']; dup=Counter(e['key'] for e in entries)
        con.execute('INSERT INTO materials VALUES (?,?,?,?,?)', (mid,m['name'],m['type'],json.dumps(m['origins']),json.dumps(m['warnings'])))
        rows=[]; array_status={}; arrays={}
        def issue(key,code,detail):
            issues[code]+=1
            con.execute('INSERT INTO issues VALUES (?,?,?,?)',(mid,key,code,detail))
        for ordinal,e in enumerate(entries):
            key,raw=e['key'],e['value']; match=re.fullmatch(r'(.+)\[(\d+)\]',key)
            base,idx=(match[1],int(match[2])) if match else (key,None)
            value=unit=None; quality='unvalidated'
            if base in TEXT: status='metadata'; quality='not_applicable'
            elif base in SELECTORS: status='source_selector'; quality='not_applicable'
            elif base not in RULES: status='unit_unverified'
            else:
                unit=RULES[base]['si_unit']
                try:
                    value,x=si(raw,RULES[base]); status='normalized'; converted+=1
                    if idx is None and base in POSITIVE and x<=0:
                        quality='nonpositive_requires_review';issue(key,quality,raw)
                except (InvalidOperation,ValueError):
                    status='invalid_numeric'; value=None; issue(key,status,raw)
            if '=' in raw and base not in TEXT:
                issue(key,'embedded_assignment',raw);quality='malformed_source';value=None;status='invalid_source'
            if dup[key]>1:
                issue(key,'duplicate_key',raw);quality='duplicate_requires_review';value=None;status='ambiguous_duplicate'
            if idx is not None:
                arrays.setdefault(base,[]).append(idx);array_status[(base,idx)]=status
            rows.append((mid,ordinal,key,base,idx,raw,value,unit,status,quality));statuses[status]+=1
            audit=field_audit.setdefault(base,{'occurrences':0,'statuses':Counter(),'example':raw[:180]})
            audit['occurrences']+=1;audit['statuses'][status]+=1
        con.executemany('INSERT INTO fields VALUES (?,?,?,?,?,?,?,?,?,?)',rows)
        malformed=any('=' in e['value'] and e['key'] not in TEXT for e in entries)
        for kind,keys in CURVES.items():
            if not any(k in arrays for k in keys):continue
            inds=[arrays.get(k,[]) for k in keys]; sets=[set(i) for i in inds]
            aligned=all(s==sets[0] for s in sets) and all(len(a)==len(set(a)) for a in inds)
            contiguous=all(sorted(s)==list(range(len(s))) for s in sets)
            normalized=not malformed and aligned and contiguous and all(array_status[(k,i)]=='normalized' for k in keys for i in arrays.get(k,[]))
            detail={'axes':keys,'indices_match':aligned,'contiguous':contiguous,'source_order_preserved':True,
                    'interpolation':'not_performed','physical_validation':'not_performed'}
            status='normalized_structural_only' if normalized else 'requires_review'
            if not normalized:issue(kind,'curve_structure_requires_review',json.dumps(detail))
            con.execute('INSERT INTO curves VALUES (?,?,?,?,?)',(mid,kind,len(set.intersection(*sets)),status,json.dumps(detail)))
    con.executescript('CREATE INDEX fields_lookup ON fields(material_id,base_key,array_index); CREATE INDEX materials_name ON materials(name);')
    con.commit()
    assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    # Independent readback compares every raw entry and the inverse SI conversion.
    verified=0; reverse_checked=0
    for m in payload['materials']:
        actual=con.execute('SELECT raw_key,raw_value,base_key,si_value_decimal FROM fields WHERE material_id=? ORDER BY ordinal',(m['id'],)).fetchall()
        assert len(actual)==len(m['raw_entries'])
        for (key,raw,base,y),original in zip(actual,m['raw_entries']):
            assert (key,raw)==(original['key'],original['value']);verified+=1
            if y is not None:
                with localcontext() as ctx:
                    ctx.prec=max(80,len(raw)+40); spec=RULES[base]
                    assert (Decimal(y)-Decimal(spec['offset']))/Decimal(spec['factor'])==Decimal(raw.strip())
                reverse_checked+=1
    curve_counts=dict(con.execute('SELECT status,count(*) FROM curves GROUP BY status'))
    material_counts=dict(con.execute('SELECT type,count(*) FROM materials GROUP BY type'))
    con.close()
    staging.replace(OUT/'materials_si.sqlite')
    write_json(OUT/'unit_registry.json', RULES)
    write_json(OUT/'field_audit.json', field_audit)
    summary={'materials':len(payload['materials']), 'types':material_counts,'field_status_counts':dict(statuses),
             'issue_counts':dict(issues),'curve_status_counts':curve_counts,'raw_fields_readback_verified':verified,
             'exact_inverse_conversions_verified':reverse_checked,'sqlite_integrity':'ok',
             'representative_materials_selected':0,'source_json_sha256':metadata['source_json_sha256']}
    write_json(OUT/'normalization_report.json',summary)
    return summary

def archive(source, dest):
    files=sorted(p for p in source.rglob('*') if p.is_file())
    manifest={p.relative_to(source).as_posix():{'sha256':sha(p),'bytes':p.stat().st_size} for p in files}
    with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9,allowZip64=True) as z:
        for p in files:z.write(p,p.relative_to(source).as_posix())
        z.writestr('SHA256_MANIFEST.json',json.dumps(manifest,indent=2))
    # Read back every decompressed byte: validates CRC and SHA-256, including every MDB/GDB.
    with zipfile.ZipFile(dest) as z:
        for name,info in manifest.items():
            with z.open(name) as f:assert hashlib.file_digest(f,'sha256').hexdigest()==info['sha256'],name
    return {'file':str(dest),'files_verified':len(files),'uncompressed_bytes':sum(i['bytes'] for i in manifest.values()),
            'compressed_bytes':dest.stat().st_size,'sha256':sha(dest),'decompressed_sha256_check':'passed'}

if __name__=='__main__':
    print(json.dumps(build(),ensure_ascii=False),flush=True)
