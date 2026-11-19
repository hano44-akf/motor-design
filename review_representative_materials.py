from pathlib import Path
from collections import defaultdict
from statistics import median
import json,re

ROOT=Path(__file__).resolve().parent
p=json.loads((ROOT/'material_library/20261019_161745/materials_raw.json').read_text(encoding='utf-8'))
recent={g['export_sha256'] for g in p['granta_provenance'] if '20261019_131932' in g['report_path']}
byname=defaultdict(list)
for m in p['materials']:byname[m['name']].append(m)
def chosen(ms):return sorted(ms,key=lambda m:(any(o['database_sha256'] in recent for o in m['origins']),m['id']),reverse=True)[0]
materials=[chosen(ms) for ms in byname.values()]
def fields(m):return {e['key']:e['value'] for e in m['raw_entries']}
def num(m,k):
 try:return float(fields(m)[k])
 except (ValueError,KeyError):return None
def interp(pairs,x):
 pts=sorted(set(pairs))
 for a,b in pts:
  if a==x:return b
 for (a,b),(aa,bb) in zip(pts,pts[1:]):
  if a<x<aa:return b+(bb-b)*(x-a)/(aa-a)
 return None
def xy(m,xkey,ykey):
 a=m['indexed_arrays'];xd={v['index']:float(v['raw_value']) for v in a.get(xkey,[])};yd={v['index']:float(v['raw_value']) for v in a.get(ykey,[])}
 return [(xd[i],yd[i]) for i in sorted(xd.keys()&yd.keys())]
def magnet_b(m,t,h):
 a=m['indexed_arrays'];ts={v['index']:float(v['raw_value']) for v in a.get('Temperature',[])}
 hs={v['index']:float(v['raw_value']) for v in a.get('HValue_Magnet',[])};bs={v['index']:float(v['raw_value']) for v in a.get('BValue_Magnet',[])}
 return interp([(hs[i],bs[i]) for i in ts.keys()&hs.keys()&bs.keys() if ts[i]==t],h)
def loss(m,f,b):
 a=m['indexed_arrays'];fs={v['index']:float(v['raw_value']) for v in a.get('Frequency',[])};bs={v['index']:float(v['raw_value']) for v in a.get('FluxDensity',[])};ls={v['index']:float(v['raw_value']) for v in a.get('LossDensity',[])}
 return interp([(bs[i],ls[i]) for i in fs.keys()&bs.keys()&ls.keys() if fs[i]==f],b)
def range_(xs):
 xs=[x for x in xs if x is not None];return [min(xs),median(xs),max(xs)] if xs else None
rows=[]
for m in materials:
 match=re.fullmatch(r'JL Mag Rare-Earth \| N(\d+)(SH|UH)',m['name'])
 if not match or not 30<=int(match[1])<=52:continue
 product=m['name'].split('|')[-1].strip()
 peers=[x for x in materials if '|' in x['name'] and not x['name'].startswith('JL Mag') and x['name'].split('|')[-1].strip()==product and num(x,'MagnetRefTemp')==20]
 b100=magnet_b(m,100,-400000);temps=sorted({float(x['raw_value']) for x in m['indexed_arrays'].get('Temperature',[])})
 rows.append({'name':m['name'],'id':m['id'],'Br20_T':num(m,'MagnetBrValue'),'Hcj20_kAm':num(m,'MagnetHcJValue')/1000,
 'curve_temperatures_C':temps,'peer_names':[x['name'] for x in peers],
 'peer_Br20_min_median_max_T':range_([num(x,'MagnetBrValue') for x in peers]),
 'B_100C_Hminus400kAm_T':b100,
 'peer_B_100C_Hminus400kAm_min_median_max_T':range_([magnet_b(x,100,-400000) for x in peers]),
 'curve_point_count':len(m['indexed_arrays'].get('Temperature',[]))})
rows.sort(key=lambda r:(int(re.search(r'N(\d+)',r['name'])[1]),r['name']))
steel=[]
for m in materials:
 if not m['name'].startswith('POSCO |'):continue
 steel.append({'name':m['name'],'id':m['id'],'thickness_mm':num(m,'LaminationThickness'),
 'loss_50Hz_1p5T_Wkg':loss(m,50,1.5),'loss_60Hz_1p5T_Wkg':loss(m,60,1.5),
 'B_at_5000Am_T':interp(xy(m,'HValue','BValue'),5000),'notes':fields(m).get('Notes','')})
comparison={}
for t in [0.35,0.5]:
 peers=[m for m in materials if m['type']=='Steel' and '|' in m['name'] and not m['name'].startswith('POSCO |') and num(m,'LaminationThickness')==t]
 comparison[str(t)]={'peer_count':len(peers),'loss50_1p5_range':range_([loss(m,50,1.5) for m in peers]),'B5000_range':range_([interp(xy(m,'HValue','BValue'),5000) for m in peers])}
out=ROOT/'outputs/representative_review_20261020';out.mkdir(exist_ok=True)
result={'method':'Exact named grade peers with explicit manufacturer, one record per name preferring latest API export. Linear interpolation only within available H/B range, no temperature/frequency extrapolation. Comparison is a consistency screen, not certification.',
 'JL':rows,'POSCO':steel,'steel_peers':comparison}
(out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True,indent=2))
