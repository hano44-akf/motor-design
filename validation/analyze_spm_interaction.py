"""Audit focused interaction DOE; can follow a running batch without launching FEA."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from analyze_detailed_spm import METRICS,matrix
from plan_spm_interaction import basis
from study_io import write_json


def read_cases(folder,cases,completed):
    data={};hashes={}
    for c in cases:
        if c['id'] not in completed:raise ValueError('Requested incomplete case')
        path=folder/(c['id']+'.json');raw=path.read_bytes();r=json.loads(raw)
        if r['doe_role']!=c['role'] or r['doe_point']!=c['point'] or r['native_recipe']!=c['recipe']:
            raise ValueError('Case provenance mismatch: '+c['id'])
        if r['values']!=completed[c['id']]['values']:raise ValueError('Run summary differs from source')
        for k,v in r['geometry_mm'].items():
            if abs(v-c['recipe']['native_variables'][k])>1e-6:raise ValueError('Geometry mismatch')
        data[c['id']]=r;hashes[str(path.resolve())]=hashlib.sha256(raw).hexdigest()
    return data,hashes


def audit(folder):
    folder=Path(folder);plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    parent=Path(plan['source_folder']);praw=(parent/'plan.json').read_bytes()
    if hashlib.sha256(praw).hexdigest()!=plan['source_plan_sha256']:raise ValueError('Parent plan changed')
    oldplan=json.loads(praw);oldresult=json.loads((parent/'result.json').read_text(encoding='utf-8'))
    progress=json.loads((folder/'progress.json').read_text(encoding='utf-8'))
    resultpath=folder/'result.json' if (folder/'result.json').exists() else folder/'partial_results.json'
    raw=json.loads(resultpath.read_text(encoding='utf-8')) if resultpath.exists() else []
    rows=raw['runs'] if isinstance(raw,dict) else raw
    completed={r['id']:r for r in rows};oldcompleted={r['id']:r for r in oldresult['runs']}
    groups=[];waiting=[];hashes={}
    for g in plan['groups']:
        if not all(c['id'] in completed for c in g['cases']):waiting.append(g['shape']);continue
        old=next(o for o in oldplan['groups'] if o['shape']==g['shape'])
        ocases=[c for c in old['cases'] if c['role']!='independent_holdout']
        olddata,h=read_cases(parent,ocases,oldcompleted);hashes.update(h)
        newdata,h=read_cases(folder,g['cases'],completed);hashes.update(h)
        all_data={**olddata,**newdata}
        train=ocases+[c for c in g['cases'] if c['role']=='training_interaction']
        hold=[c for c in g['cases'] if c['role']=='independent_holdout']
        def points(cases):return np.array([[(c['point'][key]-center)/delta for key,center,delta in g['factors']] for c in cases])
        oldx=points(ocases);x=points(train);hx=points(hold)
        a=basis(x)
        if np.linalg.matrix_rank(a)!=10:raise ValueError('Interaction design lost rank')
        metrics={}
        for key,native in METRICS.items():
            y=np.array([all_data[c['id']]['values'][native] for c in train],dtype=float)
            actual=np.array([newdata[c['id']]['values'][native] for c in hold],dtype=float)
            oldy=np.array([olddata[c['id']]['values'][native] for c in ocases],dtype=float)
            if not np.all(np.isfinite(np.r_[y,actual,oldy])):raise ValueError('Non-finite response')
            models={}
            for name,design,observed,hdesign in [('old_additive_quadratic',matrix(oldx,True),oldy,matrix(hx,True)),
                ('augmented_additive_quadratic',matrix(x,True),y,matrix(hx,True)),
                ('focused_interaction',a,y,basis(hx))]:
                coeff=np.linalg.lstsq(design,observed,rcond=None)[0];pred=hdesign@coeff;err=pred-actual
                models[name]={'coefficients':coeff.tolist(),'training_count':len(observed),
                    'holdout_prediction':pred.tolist(),'holdout_actual':actual.tolist(),
                    'max_abs_error':float(np.max(np.abs(err))),
                    'max_relative_error_pct':float(np.max(np.abs(err)/np.maximum(np.abs(actual),1e-12))*100),
                    'rmse':float(np.sqrt(np.mean(err**2))),'qualified':False}
            metrics[key]=models
        newcases=list(newdata.values())
        bkeys=['Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)',
            'Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)']
        groups.append({'shape':g['shape'],'training_count':13,'new_holdout_ids':[c['id'] for c in hold],
            'rank':10,'training_residual_degrees_of_freedom':3,'metrics':metrics,
            'observed_new_ranges':{k:{'min':min(r['values'][k] for r in newcases),'max':max(r['values'][k] for r in newcases)} for k in
                ['Torque Ripple (MsVw) [%]','Stator Tooth Flux Density (maximum)','Stator Back Iron Flux Density (maximum)']},
            'new_ripple_pass_count':sum(r['values']['Torque Ripple (MsVw) [%]']<=20 for r in newcases),
            'new_B_pass_count':sum(max(r['values'][k] for k in bkeys)<=1.8 for r in newcases),
            'production_model_activated':False,'ripple_predictor_fitted':False})
    return {'schema':'spm-focused-interaction-audit-v1','source_folder':str(folder.resolve()),
        'batch_status':progress['status'],'completed_fea':len(rows),'planned_fea':plan['planned_fea'],
        'status':'complete' if not waiting else 'partial','groups':groups,'waiting_shapes':waiting,'source_sha256':hashes,
        'new_fea_started_by_analysis':0,'limitations':['Only one of six pairwise interactions is modeled.',
            'Three fresh holdouts per shape, not reliability certification.',
            'Old holdouts informed experiment selection and are not reused for fitting or called fresh validation.',
            'Coefficients and errors are diagnostic only; no engine activation, input-bound change or ripple surrogate.',
            'Fixed current, speed, geometry envelope, temperature and winding; cannot generalize to requested-torque optimization.']}


def report(data,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True);write_json(output/'analysis.json',data)
    lines=['# 치 폭·슬롯 깊이 조합 효과 분석','',
        f"해석 배치 상태: {data['batch_status']}. 완료 {data['completed_fea']}/{data['planned_fea']}회. 분석 상태: {data['status']}.",
        '분석기는 Motor-CAD 해석을 시작하지 않는다. 형상별7점이 모두 저장된 경우에만 해당 형상을 분석한다.', '',
        '기존 학습9점+새 조합4점으로 학습13점을 구성했다. 새 확인3점은 학습에서 제외했다. 같은13점에 교차항 없는 가산2차식도 맞춰 비교해, 데이터 추가 효과와 교차항 추가 효과를 구분한다.', '',
        '| 형상 | 출력 | 기존9점 가산2차 최대 오차 | 13점 가산2차 최대 오차 | 13점 교차항 포함 최대 오차 |',
        '|---|---|---:|---:|---:|']
    for g in data['groups']:
        for key,models in g['metrics'].items():
            vals=[models[n]['max_abs_error'] for n in ('old_additive_quadratic','augmented_additive_quadratic','focused_interaction')]
            lines.append(f"| {g['shape']} | {key} | "+' | '.join(f'{v:.6g}' for v in vals)+' |')
        lines+=['',f"{g['shape']}: 새7점 중 리플20% 통과 {g['new_ripple_pass_count']}점, 최대B1.8T 통과 {g['new_B_pass_count']}점.", '']
    lines+=['','효율 오차는 %p, 나머지는 출력 자체의 단위다. 확인점3개에서 오차가 작아도 생산용 모델 인증으로 취급하지 않는다. 열·구조·스큐는 제외하며 리플 예측 모듈도 보류 상태다.',
        '', '다음 판단은 두 형상 완료 후 확인점 오차와 포화 결과를 함께 검토하는 것이다. 교차항이 일관되게 유리하지 않으면 복잡한 모델을 채택하지 않는다. B와 리플을 만족하는 설계를 확보했다고 주장하지 않는다.']
    if data['waiting_shapes']:lines+=['','미완료 형상: '+', '.join(data['waiting_shapes'])+'. 기존 워커 종료 후 자동 분석을 갱신할 수 있다.']
    (output/'REVIEW_KO.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def run(source,output,follow=False):
    started=time.time()
    while True:
        data=audit(source);report(data,output)
        if not follow or data['batch_status'] in ('completed','completed_with_blocked_cases','failed','stopped'):return
        if time.time()-started>7200:raise TimeoutError('Postprocessing follow deadline exceeded; no native action taken')
        time.sleep(30)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--follow',action='store_true')
    a=p.parse_args();run(a.source,a.output,a.follow)
