"""Small new-domain magnetic pilot proposal; no performance extrapolation."""
import copy
import itertools
import json
from pathlib import Path
from detailed_spm_recipe import compile_recipe
from study_io import write_json


def make_plan(source):
    source=Path(source);old=json.loads((source/'plan.json').read_text(encoding='utf-8'))
    groups=[]
    for previous in old['groups']:
        request=copy.deepcopy(previous['request'])
        request['geometry_parameters'].update({'tooth_width_mm':{'mode':'range','min':7.5,'max':8.1},
            'slot_depth_mm':{'mode':'range','min':8.8,'max':9.4},'slot_opening_mm':{'mode':'fixed','value':2.4}})
        request['spm']['parameters']['pole_arc_ed']={'mode':'fixed','value':110}
        cases=[]
        for i,(width,depth) in enumerate(itertools.product((7.5,8.1),(8.8,9.4))):
            point={'tooth_width_mm':width,'slot_depth_mm':depth}
            cases.append({'id':previous['shape'].lower()+'_rangeprobe_'+str(i+1).zfill(2),
                'role':'new_domain_pilot','point':point,'recipe':compile_recipe(request,point),
                'state':'proposed_not_executed','performance_prediction':None})
        groups.append({'shape':previous['shape'],'request':request,'cases':cases,'planned_fea':4,'mapping_save_readback_checks':1})
    return {'schema':'spm-new-domain-pilot-v1','state':'proposed_not_executed','planned_fea':8,'executed_fea':0,
        'groups':groups,'flux_density_limit_T':1.8,'estimated_minutes':[45,60],
        'purpose':'Check a wider-tooth/thicker-yoke local domain before defining a new calibration DOE.',
        'qualification':False,'production_input_bounds_changed':False,
        'limitations':['Engineering pilot bounds, not manufacturer-approved or analytically certified values.',
            'Only necessary envelope checks passed; exact slot area, fill, tip B, voltage and ripple require native evaluation.',
            'Existing regressions must not extrapolate into this domain.',
            'Four points per shape are a screen, not a surrogate calibration or independent validation set.',
            'Keep D85 L20 gap0.5, magnet2.6, 40A linepeak, 3500rpm 20C Delta unchanged; not target-torque optimization.',
            'No automatic FEA launch. Breadloaf, thermal, structural and skew are not part of this pilot.']}


if __name__=='__main__':
    root=Path(__file__).resolve().parent.parent
    output=root/'outputs/spm_new_domain_plan_20261103';output.mkdir(parents=True,exist_ok=True)
    plan=make_plan(root/'outputs/motorcad_spm_interaction_20261103_080325');write_json(output/'plan.json',plan)
    print(json.dumps({'planned_fea':8,'executed_fea':0,'output':str(output)}))
