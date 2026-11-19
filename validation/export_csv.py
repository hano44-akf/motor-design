"""Export saved run/prediction JSON without launching Motor-CAD.

Usage: python validation/export_csv.py INPUT.json --output-dir exports
Produces UTF-8 BOM CSVs and a strict JSON bundle usable by the UI.
"""
import argparse
import csv
import json
import math
from pathlib import Path
from csv_metadata import metadata as quantity_metadata

def flatten(value, prefix=''):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from flatten(child, f'{prefix}.{key}' if prefix else str(key))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from flatten(child, f'{prefix}[{i}]')
    else:
        yield prefix, value

def clean(value):
    if isinstance(value, dict):
        return {k:clean(v) for k,v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):
        return str(value)  # Preserve nonfinite state explicitly, never replace with zero.
    return value

def cell(value):
    if value is None:
        return ''
    if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):
        return "'"+value
    return value

def export(source, output):
    data=clean(json.loads(source.read_text(encoding='utf-8-sig')))
    if not isinstance(data,dict):
        raise ValueError('Expected a JSON object')
    output.mkdir(parents=True,exist_ok=True)
    groups={'inputs':data.get('design',data.get('inputs',{})),
            'results':data.get('predictions',data.get('results',{})),
            'motorcad':data.get('values',{})}
    metadata={k:v for k,v in data.items() if k not in ('design','inputs','predictions','results','values')}
    for group,content in groups.items():
        with (output/f'{source.stem}_{group}.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f)
            writer.writerow(['source_file','category','field','value','data_status','unit','basis','condition_id','evidence'])
            status='saved_MotorCAD_output' if group=='motorcad' and content else 'prediction' if group=='results' and 'predictions' in data else 'saved_input_or_metadata'
            for key,value in flatten(content):
                unit,basis=quantity_metadata(key)
                writer.writerow([cell(source.name),group,cell(key),cell(value),status,unit,basis,'see_field_path',status])
            for key,value in flatten(metadata,'metadata'):
                unit,basis=quantity_metadata(key)
                writer.writerow([cell(source.name),'metadata',cell(key),cell(value),'source_metadata',unit,basis,'see_field_path','source_metadata'])
    bundle={'schema':'motor-csv-export-v1','source_file':source.name,'data':data}
    (output/f'{source.stem}_bundle.json').write_text(json.dumps(bundle,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--output-dir',type=Path,default=Path('exports'))
    args=parser.parse_args()
    export(args.source,args.output_dir)
