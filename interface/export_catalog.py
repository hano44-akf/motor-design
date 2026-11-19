import sqlite3,json,pathlib
root=pathlib.Path(__file__).resolve().parent
c=sqlite3.connect(f'file:{root.parent.as_posix()}/material_library/normalized_20261020/materials_si.sqlite?mode=ro',uri=True)
d={}
for mid,name in c.execute("select id,name from materials where type='Steel'"):
    if 'posco' in name.lower(): d.setdefault(name,[]).append(mid)
catalog=[dict(name=n,grade=n.split('|')[-1].strip(),ids=ids) for n,ids in sorted(d.items())]
(root/'steel-catalog.js').write_text('const steelCatalog='+json.dumps(catalog,ensure_ascii=False)+';',encoding='utf-8')
print(json.dumps(catalog,ensure_ascii=False,indent=2))
