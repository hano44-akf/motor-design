from normalize_materials import ROOT, SOURCE, OUT, archive, write_json
from pathlib import Path
import shutil
import json

if __name__=='__main__':
    report=json.loads((OUT/'normalization_report.json').read_text(encoding='utf-8'))
    assert report['sqlite_integrity']=='ok'
    for name in ('normalize_materials.py','test_normalization.py','package_materials.py'):
        shutil.copyfile(ROOT/name,OUT/name)
    dest=ROOT/'material_packages';dest.mkdir(exist_ok=True)
    results=[]
    for source,name in [(SOURCE,'motorcad_original_20261020.zip'),(OUT,'motorcad_normalized_20261020.zip')]:
        print('Compressing and verifying '+name,flush=True)
        result=archive(source,dest/name);results.append(result)
        print(json.dumps(result),flush=True)
    write_json(dest/'compression_report.json',{'status':'passed','archives':results,'originals_deleted':False})
