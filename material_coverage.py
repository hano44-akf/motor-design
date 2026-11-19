"""Read-only material coverage audit. No representative selection or interpolation."""
from pathlib import Path
from collections import Counter, defaultdict
from decimal import Decimal
import sqlite3, json, re, hashlib

ROOT=Path(__file__).resolve().parent
DB=ROOT/'material_library/normalized_20261020/materials_si.sqlite'
OUT=ROOT/'outputs/material_coverage_20261020'
TEMPS=[20,60,80,100,120,150,180,200]
FREQS=[50,60,100,200,400,500,1000,2000]

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(f'file:{DB.as_posix()}?mode=ro',uri=True)
    material={r[0]:dict(id=r[0],name=r[1],type=r[2],fields={},arrays=defaultdict(dict),issues=[],curves={}) for r in c.execute('select id,name,type from materials')}
    for mid,key,idx,raw,si,status,quality in c.execute('select material_id,base_key,array_index,raw_value,si_value_decimal,status,quality from fields'):
        value=Decimal(si) if si is not None else None
        if idx is None:material[mid]['fields'][key]=(raw,value,status,quality)
        else:material[mid]['arrays'][key][idx]=value
    for mid,key,code,detail in c.execute('select * from issues'):
        material[mid]['issues'].append((key,code,detail))
    for mid,kind,n,status,detail in c.execute('select * from curves'):
        material[mid]['curves'][kind]=(n,status)
    namecounts=Counter(m['name'] for m in material.values())
    magnets=[];steels=[];mtemps=Counter();sfreqs=Counter();thickness=Counter();gradegroups=defaultdict(list)
    def scalar(m,k):
        v=m['fields'].get(k)
        return float(v[1]) if v and v[1] is not None and v[3]=='unvalidated' else None
    def raw(m,k):return m['fields'].get(k,('',None,None,None))[0]
    def rng(values):return (min(values),max(values)) if values else (None,None)
    def coverage(x,values,blocked=False):
        if blocked:return '검토 필요'
        if x in values:return '직접 있음'
        if values and min(values)<x<max(values):return '사이(미보간)'
        return '없음'
    def faults(m):
        bad=any(i[1] in ('embedded_assignment','duplicate_key','curve_structure_requires_review') for i in m['issues'])
        n=sum(i[1]=='nonpositive_requires_review' for i in m['issues'])
        return bad,('원본 구조 이상' if bad else '구조 이상 없음'),n
    for m in material.values():
        if m['type'] not in ('Magnet','Steel'):continue
        name=m['name']; notes=raw(m,'Notes'); a=m['arrays'];bad,state,nzero=faults(m)
        maker=name.split('|',1)[0].strip() if '|' in name else '미분리(원문 참조)'
        family='기타/미확인'
        for marker,label in [('neodymium','네오디뮴'),('samarium','사마륨 코발트'),('bonded','본드/몰드'),('ferrite','페라이트'),('alnico','알니코')]:
            if marker in notes.lower():family=label;break
        if 'bonded' in notes.lower() or 'molded' in notes.lower():family='본드/몰드'
        if m['type']=='Magnet':
            product=name.split('|')[-1].strip()
            match=re.search(r'(?<![A-Za-z0-9])N(\d{2})([A-Za-z]*)(?![A-Za-z0-9])',product)
            if not match and family=='네오디뮴':match=re.search(r'(?<![A-Za-z0-9])(\d{2})([A-Za-z]+)(?![A-Za-z0-9])',product)
            grade=int(match[1]) if match else None;suffix=match[2].upper() or '접미 없음' if match else '미분류'
            if family=='기타/미확인' and match:family='N표기(계열 미확인)'
            grouped=defaultdict(list)
            for i,t in a.get('Temperature',{}).items():
                h=a.get('HValue_Magnet',{}).get(i); b=a.get('BValue_Magnet',{}).get(i)
                if t is not None and h is not None and b is not None:grouped[float(t-Decimal('273.15'))].append((h,b))
            valid={t:p for t,p in grouped.items() if len(set(h for h,b in p))>=2}
            validtemps=sorted(valid) if not bad else []
            for t in validtemps:mtemps[t]+=1
            lo,hi=rng(validtemps);points=sum(map(len,grouped.values()));minpoints=min(map(len,valid.values()),default=0)
            reference=scalar(m,'MagnetRefTemp');reference=round(reference-273.15,8) if reference is not None else None
            vmin=scalar(m,'ValidMagnetTemperature_Min');vmax=scalar(m,'ValidMagnetTemperature_Max')
            record=[name,maker,family,grade,suffix,'예' if grade is not None and 30<=grade<=45 else '아니오',
                    len(validtemps),lo,hi,points,minpoints,*[coverage(t,validtemps,bad) for t in TEMPS],
                    scalar(m,'MagnetBrValue'),reference,scalar(m,'MagnetHcJValue'),scalar(m,'MagneturValue'),
                    round(vmin-273.15,8) if vmin is not None else None,round(vmax-273.15,8) if vmax is not None else None,
                    ', '.join(f'{t:g}' for t in validtemps) or '없음',state,nzero,namecounts[name],notes,m['id']]
            magnets.append(record)
            if grade is not None and 30<=grade<=45:gradegroups[(grade,suffix)].append(record)
        else:
            grouped=defaultdict(list)
            for i,f in a.get('Frequency',{}).items():
                b=a.get('FluxDensity',{}).get(i);loss=a.get('LossDensity',{}).get(i)
                if f is not None and b is not None and loss is not None:grouped[float(f)].append((b,loss))
            valid={f:p for f,p in grouped.items() if f>0 and len(set(b for b,loss in p))>=2}
            freqs=sorted(valid) if not bad else []
            for f in freqs:sfreqs[f]+=1
            thick=scalar(m,'LaminationThickness');thick=round(thick*1000,8) if thick is not None else None
            thickness[thick]+=1
            bh=m['curves'].get('steel_bh',(0,''));bhok=bh[0]>=2 and bh[1]=='normalized_structural_only' and not bad
            fmin,fmax=rng(freqs)
            bvalues=[float(b) for f in freqs for b,loss in valid[f]];bmin,bmax=rng(bvalues)
            detail='; '.join(f'{f:g}Hz: {min(b for b,l in valid[f]):g}~{max(b for b,l in valid[f]):g}T, {len(valid[f])}점' for f in freqs) or '없음'
            steels.append([name,maker,thick,'있음' if bhok else ('검토 필요' if bad else '없음'),bh[0],
                len(freqs),fmin,fmax,sum(map(len,grouped.values())),bmin,bmax,*[coverage(f,freqs,bad) for f in FREQS],
                ', '.join(f'{f:g}' for f in freqs) or '없음',detail,scalar(m,'Density'),state,nzero,namecounts[name],notes,m['id']])
    magnets.sort(key=lambda r:(r[3] if r[3] is not None else 999,r[4],r[0],r[-1]))
    steels.sort(key=lambda r:(r[2] if r[2] is not None else 999,r[0],r[-1]))
    mag_headers=['재질명','제조사 표기','계열 표기','등급 숫자','등급 접미','N30~45 표기','곡선 온도 수','곡선 최저 °C','곡선 최고 °C','BH 점 수','온도당 최소 점 수',*[f'{t}°C' for t in TEMPS],'Br T','Br 기준 °C','Hcj A/m','상대 투자율','원본 유효 최저 °C','원본 유효 최고 °C','직접 온도 목록 °C','구조 상태','비양수 검토 필드 수','동일명 버전 수','원본 주석','재질 ID']
    steel_headers=['재질명','제조사 표기','판두께 mm','BH 보유','BH 점 수','철손 주파수 수','철손 최저 Hz','철손 최고 Hz','철손 점 수','철손 B 최저 T','철손 B 최고 T',*[f'{f}Hz' for f in FREQS],'직접 주파수 목록 Hz','주파수별 B 범위와 점 수','밀도 kg/m3','구조 상태','비양수 검토 필드 수','동일명 버전 수','원본 주석','재질 ID']
    groups=[]
    for (g,s),rs in sorted(gradegroups.items()):
        groups.append([g,s,len(rs),sum(r[6]>0 for r in rs),*[sum(r[11+i]=='직접 있음' for r in rs) for i in range(len(TEMPS))]])
    totals={'magnet_records':len(magnets),'steel_records':len(steels),'magnet_names':len({r[0] for r in magnets}),
        'steel_names':len({r[0] for r in steels}),'magnets_with_curves':sum(r[6]>0 for r in magnets),
        'magnets_with_2plus_temperatures':sum(r[6]>=2 for r in magnets),'magnets_curve_minpoints_le3':sum(0<r[10]<=3 for r in magnets),
        'steel_with_bh':sum(r[3]=='있음' for r in steels),'steel_with_loss':sum(r[5]>0 for r in steels),
        'steel_with_both':sum(r[3]=='있음' and r[5]>0 for r in steels),'N30_45_records':sum(r[5]=='예' for r in magnets)}
    for records,headers in [(magnets,mag_headers),(steels,steel_headers)]:assert all(len(r)==len(headers) for r in records)
    assert len(magnets)==1292 and len(steels)==284
    output={'totals':totals,'temperatures':TEMPS,'frequencies':FREQS,'magnet_headers':mag_headers,'magnets':magnets,
        'steel_headers':steel_headers,'steels':steels,'grade_groups':groups,
        'temperature_summary':[[t,mtemps[t],sum(r[11+i]=='사이(미보간)' for r in magnets)] for i,t in enumerate(TEMPS)],
        'frequency_summary':[[f,sfreqs[f],sum(r[11+i]=='사이(미보간)' for r in steels)] for i,f in enumerate(FREQS)],
        'all_temperature_counts':sorted(mtemps.items()),'all_frequency_counts':sorted(sfreqs.items()),
        'thickness_summary':[[k,v] for k,v in sorted(thickness.items(),key=lambda x: x[0] if x[0] is not None else 999)],
        'source_db_sha256':hashlib.sha256(DB.read_bytes()).hexdigest()}
    (OUT/'coverage_data.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in output.items() if k in ('totals','temperature_summary','frequency_summary','thickness_summary')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
