"""Finite, proposed pilot DOE. Not a qualified model or executable FEA queue."""
import copy
import json
from pathlib import Path
from detailed_spm_recipe import compile_recipe
from dimension_grid import mm
from verification_scope import POLICY


def make_plan():
    groups=[]
    for shape in ('Radial','Parallel','Breadloaf'):
        factors=[('tooth_width_mm',6.9,.6),('slot_depth_mm',10,.6),
                 ('slot_opening_mm',2,.4),('pole_arc_ed',120,10)]
        if shape=='Breadloaf':factors.append(('magnet_reduction_mm',.4,.2))
        r={'spm':{'shape':shape,'magnetisation':'Parallel' if shape=='Parallel' else 'Radial','parameters':{}},
           'core':'POSCO | 50PN470','dimensions':{'diameter_mm':85,'length_mm':20},
           'airgap_bounds_mm':[.5,.5],'pole_slot_candidates':[{'poles':4,'slots':12}],
           'geometry_parameters':{}}
        for key,center,delta in factors:
            group=r['spm']['parameters'] if key in ('pole_arc_ed','magnet_reduction_mm') else r['geometry_parameters']
            group[key]={'mode':'range','min':mm(center-delta),'max':mm(center+delta)}
        vectors=[('training_center',[0]*len(factors))]
        for index in range(len(factors)):
            for sign in (-1,1):
                vector=[0]*len(factors);vector[index]=sign
                vectors.append(('training_axis',vector))
        for index in range(3):
            vectors.append(('independent_holdout',[.5 if (j+index)%3==0 else -.5 for j in range(len(factors))]))
        cases=[]
        for index,(role,vector) in enumerate(vectors):
            point={key:mm(center+delta*z) for (key,center,delta),z in zip(factors,vector)}
            recipe=compile_recipe(r,point)
            cases.append({'id':shape.lower()+'_'+str(index+1).zfill(2),'role':role,
                          'point':point,'recipe':recipe,'state':'proposed_not_executed'})
        groups.append({'shape':shape,'factor_count':len(factors),'factors':factors,'request':r,
            'mapping_save_readback_checks':1,'training_fea':1+2*len(factors),'holdout_fea':3,
            'planned_fea':len(cases),'cases':cases})
    return {'schema':'detailed-spm-pilot-plan-v1','state':'proposed_not_executed',
        'mapping_save_readback_checks':len(groups),'planned_fea':sum(g['planned_fea'] for g in groups),
        'executed_fea':0,'groups':groups,'verification_policy':copy.deepcopy(POLICY),
        'purpose':'Local factor screening and testing whether a surrogate is justified. Not full topology qualification.',
        'preconditions':['Native save/reload/readback on disposable copies for all three templates.',
            'Resolve Breadloaf reduction, segmentation and exact corner geometry before Breadloaf FEA.',
            'Freeze winding, current convention, operating point, material assignment and mesh policy before execution.'],
        'outputs':['Mean electromagnetic and shaft torque','Torque peak-to-peak and explicitly defined ripple percent',
            'Tooth and yoke flux density separately','Phase resistance, back-EMF and inductance definitions',
            'Loss breakdown, efficiency, voltage and current','Applied/read-back geometry and timing'],
        'limitations':['Center plus axial perturbations cannot identify all pairwise interactions.',
            'Holdouts must not be reused for fitting; poor prediction requires additional interaction samples or a narrower domain.',
            'Three holdouts are a pilot screen, not statistical reliability certification.',
            'Do not claim torque-ripple prediction from these samples; the ripple surrogate remains deferred.',
            'Other pole/slot pairs, rotor types, manufacturing, temperature/demagnetization and final candidate checks are not counted here.',
            'No implicit current-correction repeats or mesh-refinement solves are included in the 38 scheduled evaluation points.',
            'Operating-point setup may require additional solves; total qualification solve count is not yet fixed.']}


if __name__=='__main__':
    folder=Path(__file__).resolve().parent.parent/'outputs/detailed_spm_connection_20261027'
    folder.mkdir(parents=True,exist_ok=True)
    plan=make_plan()
    (folder/'pilot_validation_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:plan[key] for key in ('mapping_save_readback_checks','planned_fea','executed_fea')}))
