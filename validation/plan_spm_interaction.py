"""Focused tooth-width / slot-depth experiment augmentation, not an optimizer."""
import argparse
import copy
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np
from detailed_spm_recipe import compile_recipe
from dimension_grid import mm
from study_io import write_json


def basis(points):
    x=np.asarray(points,dtype=float)
    return np.column_stack([np.ones(len(x)),x,x*x,x[:,0]*x[:,1]])


def make_plan(source):
    source=Path(source);old=json.loads((source/'plan.json').read_text(encoding='utf-8'))
    result=json.loads((source/'result.json').read_text(encoding='utf-8'))
    completed={r['id'] for r in result['runs']};groups=[]
    for group in old['groups']:
        if group['shape'] not in ('Radial','Parallel'):continue
        if not all(c['id'] in completed for c in group['cases']):raise ValueError('Complete source DOE required')
        factors=group['factors']
        if [f[0] for f in factors[:2]]!=['tooth_width_mm','slot_depth_mm']:raise ValueError('Unexpected factor order')
        vectors=[('training_interaction',[a,b,0,0]) for a,b in itertools.product((-1,1),repeat=2)]
        vectors += [('independent_holdout',[a,b,0,0]) for a,b in ((.5,.5),(.5,-.5),(-.5,.5))]
        cases=[];oldpoints={tuple(sorted(c['point'].items())) for c in group['cases']}
        for i,(role,z) in enumerate(vectors):
            point={key:mm(center+delta*v) for (key,center,delta),v in zip(factors,z)}
            if tuple(sorted(point.items())) in oldpoints:raise ValueError('New case duplicates old data')
            cases.append({'id':group['shape'].lower()+'_interaction_'+str(i+1).zfill(2),'role':role,
                'point':point,'recipe':compile_recipe(group['request'],point),'state':'proposed_not_executed'})
        train=[[(c['point'][key]-center)/delta for key,center,delta in factors]
            for c in group['cases'] if c['role']!='independent_holdout']
        train += [z for role,z in vectors if role=='training_interaction']
        rank=int(np.linalg.matrix_rank(basis(train)))
        if rank!=10:raise ValueError('Focused interaction model is not identifiable')
        groups.append({'shape':group['shape'],'request':copy.deepcopy(group['request']),'factors':factors,
            'factor_count':4,'mapping_save_readback_checks':1,'training_fea':4,'holdout_fea':3,
            'planned_fea':7,'cases':cases,'parent_training_case_ids':[c['id'] for c in group['cases'] if c['role']!='independent_holdout'],
            'design_audit':{'combined_training_count':len(train),'basis_rank':rank,'coefficient_count':10,
                'residual_degrees_of_freedom':len(train)-rank,'modeled_cross_term':'tooth_width_mm * slot_depth_mm'}})
    if len(groups)!=2:raise ValueError('Both qualified input mappings required')
    return {'schema':'spm-focused-interaction-plan-v1','state':'proposed_not_executed',
        'source_folder':str(source.resolve()),'source_plan_sha256':hashlib.sha256((source/'plan.json').read_bytes()).hexdigest(),
        'planned_fea':14,'executed_fea':0,'mapping_save_readback_checks':2,'groups':groups,
        'purpose':'Identify one targeted interaction while preserving new independent holdouts.',
        'unchanged_scope':'D85 L20 4p12s gap0.5, 6 turns, 1.8mm wire, line peak40A, 3500rpm, 20C, Delta.',
        'production_optimizer_connected':False,'ripple_model_deferred':True,
        'limitations':['Other five pairwise interactions remain unidentified.',
            'Three fresh holdouts per shape do not certify reliability.',
            'Previous holdouts informed experiment selection; do not present them as untouched validation.',
            'All new points remain inside the old factor bounds, but were not magnetically qualified.',
            'No evidence yet that maxB1.8T or ripple20pct can be met in this domain.',
            'No new Breadloaf FEA or thermal/structural analysis is included.'],
        'estimated_minutes':{'low':30,'high':40,'basis':'Previous 24-case batch took 56min10s, about 2.34min/case including overhead.'}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();data=make_plan(a.source);a.output.mkdir(parents=True,exist_ok=True);write_json(a.output/'plan.json',data)
    print(json.dumps({'planned_fea':data['planned_fea'],'executed_fea':0,'output':str(a.output)}))
