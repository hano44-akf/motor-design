"""Budgeted integer-neighbour search with finer ripple resolution; no Native FEA."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import time
from optimize_breadloaf_ripple import make_snapshot
from spm_ripple import predict
from breadloaf_shaft_control import solve
from breadloaf_screens import reference
from study_io import write_json

ROOT=Path(__file__).resolve().parent.parent


def neighbours(ticks,bounds):
    for axis,(lo,hi) in enumerate(bounds):
        for step in (-1,1):
            value=ticks[axis]+step
            if lo<=value<=hi:
                other=list(ticks);other[axis]=value;yield tuple(other)


def refine(study,output,max_moves=3):
    started=time.perf_counter();study=Path(study).resolve();output=Path(output).resolve()
    if isinstance(max_moves,bool) or not isinstance(max_moves,int) or not 0<=max_moves<=10:
        raise ValueError('Integer move budget 0..10 required')
    if output.exists():raise ValueError('Fresh output folder required')
    load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    previous=load(study/'result.json');plan=copy.deepcopy(previous['plan'])
    contract=plan.get('request_contract')
    if not contract:raise ValueError('Shaft request contract required')
    if hashlib.sha256(Path(plan['seed_snapshot']).read_bytes()).hexdigest()!=plan['seed_sha256']:
        raise ValueError('Seed snapshot changed since source search')
    seed=load(plan['seed_snapshot']);model=load(ROOT/'outputs/breadloaf_loss_B_validation_20261104/local_loss_B_model.json')
    if hashlib.sha256((ROOT/'outputs/breadloaf_loss_B_validation_20261104/local_loss_B_model.json').read_bytes()).hexdigest()!=plan.get('local_loss_B_model_sha256'):
        raise ValueError('Local model changed since source search')
    bounds=[(round(v['min']*10),round(v['max']*10)) for v in plan['variables']]
    ref=reference();cache={}
    if ref['sha256']!=plan['model_screen_reference']['sha256']:
        raise ValueError('Electrical reference changed since source search')
    def point(ticks):
        ticks=tuple(ticks)
        if ticks in cache:return cache[ticks]
        try:
            s=make_snapshot(seed,ticks);raw=predict(s,2880,480)
            m=solve(raw,s,contract['requested_shaft_torque_Nm'],plan['max_line_peak_A'],ref,contract,model)
            matched=m['status']=='matched_shaft_in_local_model'
            violation=m.get('model_screens',{}).get('normalized_violation',0)
            score=(0,violation,m['ripple_pct']) if matched else (1,m.get('shaft_torque_shortfall_Nm',1),m['ripple_pct'])
            if m['status']=='shaft_matching_unverified':score=(2,1,m['ripple_pct'])
            row={'ticks':list(ticks),'id':s['id'],'status':m['status'],'score':list(score),
                 'line_peak_A':m['line_peak_A'],'ripple_pct':m['ripple_pct'],
                 'predicted_shaft_torque_Nm':m.get('predicted_shaft_torque_Nm')}
        except ValueError as exc:row={'ticks':list(ticks),'status':'geometry_rejected','score':[3,1,1],'reason':str(exc)}
        cache[ticks]=row;return row
    keys=('Slot_Opening','Magnet_Arc_[ED]','MagnetReduction')
    seeds=[tuple(round(f['dimensions'][k]*10) for k in keys) for f in previous['finalists']]
    if not seeds:raise ValueError('Saved finalists required')
    incumbent=min((point(t) for t in seeds),key=lambda r:r['score']);moves=0
    for _ in range(max_moves):
        options=[incumbent]+[point(t) for t in neighbours(incumbent['ticks'],bounds)]
        best=min(options,key=lambda r:r['score'])
        if best['score']>=incumbent['score']:break
        incumbent=best;moves+=1
    selected=sorted((r for r in cache.values() if r['status']=='matched_shaft_in_local_model'),key=lambda r:r['score'])[:3]
    if not selected:raise ValueError('No shaft-matched candidate in local refinement')
    output.mkdir(parents=True);finalists=[]
    for row in selected:
        s=make_snapshot(seed,row['ticks']);levels=[]
        for spatial,rotor in ((2880,480),(5760,960)):
            raw=predict(s,spatial,rotor)
            m=solve(raw,s,contract['requested_shaft_torque_Nm'],plan['max_line_peak_A'],ref,contract,model)
            levels.append({'spatial_points':spatial,'rotor_points':rotor,**{k:v for k,v in m.items() if k!='torque_Nm'}})
        write_json(output/(s['id']+'_snapshot.json'),s)
        write_json(output/(s['id']+'_high_resolution.json'),{'raw_proxy':raw,'matched':m})
        finalists.append({'id':s['id'],'dimensions':{k:s['expected_native'][k] for k in keys},'levels':levels,
                          'selection_reason':'finer_resolution_integer_neighbour_search',
                          'last_refinement_change_percentage_points':abs(levels[-1]['ripple_pct']-levels[-2]['ripple_pct']),
                          'qualified':False,'native_geometry_readback_required':True,'native_fea_required':True})
    plan.update(algorithm='Budgeted integer axis-neighbour refinement at 2880/480, final 5760/960 check',
                source_study=str(study),source_result_sha256=hashlib.sha256((study/'result.json').read_bytes()).hexdigest(),
                max_local_moves=max_moves,completed_local_moves=moves,spatial_points=2880,rotor_points=480)
    report={'schema':'breadloaf-ripple-local-refinement-v1','plan':plan,'finalists':finalists,
            'unique_candidates':len(cache),'elapsed_s':time.perf_counter()-started,'native_fea_calls':0,
            'valid_current_matched_candidates':sum(r['status']=='matched_shaft_in_local_model' for r in cache.values()),
            'selection_status':'shaft_model_matched_candidates','qualified':False,'production_optimizer_connected':False,
            'scope':'Local integer neighbours only; not a global optimum or a full motor design qualification.'}
    write_json(output/'plan.json',plan);write_json(output/'evaluations.json',list(cache.values()))
    write_json(output/'result.json',report);write_json(output/'progress.json',{'status':'completed','elapsed_s':report['elapsed_s']})
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--study',required=True);p.add_argument('--output',required=True);p.add_argument('--max-moves',type=int,default=3)
    a=p.parse_args();r=refine(a.study,a.output,a.max_moves)
    print(json.dumps({'elapsed_s':r['elapsed_s'],'unique_candidates':r['unique_candidates'],
                      'finalists':[(f['id'],f['levels'][-1]['ripple_pct']) for f in r['finalists']]}))
