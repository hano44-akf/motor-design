"""Shared rotor schema, capability gates, draft validation and manufacturing rules.

This module never starts Motor-CAD. Registered is distinct from executable.
"""
from pathlib import Path
from functools import lru_cache
import copy
import json
import math
import re
import sqlite3
from contextlib import closing

ROOT=Path(__file__).resolve().parent.parent
CATALOG_PATH=ROOT/'interface/rotor-catalog.json'


@lru_cache(maxsize=1)
def catalog():
    data=json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
    if data['schema']!='motor-rotor-catalog-v1':raise ValueError('Unsupported rotor catalog version')
    return data


def resolve_rotor(options):
    shape=options.get('rotor_type') or options.get('shape','Radial')
    candidates=[r for r in catalog()['rotors'] if shape==r['id'] or shape==r['input_value'] or shape in r['aliases']]
    if len(candidates)!=1:raise ValueError('Unknown rotor type: '+str(shape))
    rotor=candidates[0]
    if 'rotor_type' in options and 'shape' in options:
        other=resolve_rotor({'shape':options['shape']})
        if other['id']!=rotor['id']:raise ValueError('Rotor ID and legacy shape disagree')
    return rotor


def default_magnetisation(options):
    rotor=resolve_rotor(options)
    references=[m['magnetisation'] for m in catalog()['reference_models'] if m['rotor_id']==rotor['id']]
    if len(set(references))==1:return references[0]
    directions=rotor.get('verified_magnetisation',[])
    return directions[0] if len(directions)==1 else 'Radial' if rotor['direction_policy']=='explicit' else 'Template'


def reference_model(options):
    rotor=resolve_rotor(options)
    return next((m for m in catalog()['reference_models'] if m['rotor_id']==rotor['id'] and m['magnetisation']==options.get('magnetisation',default_magnetisation(options))),None)


def _number(value,label,minimum=None):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Finite number required: '+label)
    if minimum is not None and value<minimum:raise ValueError(label+' must be >= '+str(minimum))
    return value


@lru_cache(maxsize=64)
def material_lamination_thickness(core):
    path=ROOT/'material_library/normalized_20261020/materials_si.sqlite'
    if not path.is_file() or not core:return None
    with closing(sqlite3.connect(path)) as conn:
        rows=conn.execute("SELECT f.si_value_decimal,f.si_unit FROM materials m JOIN fields f ON f.material_id=m.id WHERE m.name=? AND f.raw_key='LaminationThickness' AND f.si_value_decimal IS NOT NULL",(core,)).fetchall()
    values={round(float(v)*1000,9) for v,unit in rows if unit=='m' and float(v)>0}
    if len(values)!=1:return None
    return {'value_mm':values.pop(),'source':str(path.relative_to(ROOT)),'field':'LaminationThickness','material':core}


def manufacturing_rule(request):
    config=request.get('manufacturing') or {}
    if not isinstance(config,dict):raise ValueError('manufacturing must be an object')
    known=material_lamination_thickness(request.get('core',''))
    value=config.get('lamination_thickness_mm')
    if value is not None:
        _number(value,'lamination_thickness_mm',minimum=0)
        if value<=0:raise ValueError('Lamination thickness must be positive')
        if known and value<known['value_mm']-1e-9:raise ValueError('Lamination thickness cannot be below the selected material record')
        source='user_input'
    else:value=known['value_mm'] if known else None;source='material_library' if known else 'unavailable'
    base=catalog()['policy']['minimum_structural_section_mm']
    effective=max(base,value) if value is not None else None
    return {'base_minimum_mm':base,'lamination_thickness_mm':value,'thickness_source':source,
        'material_evidence':known,'effective_minimum_mm':effective,
        'grid_minimum_mm':math.ceil((effective-1e-9)*10)/10 if effective is not None else None,
        'status':'defined' if effective is not None else 'material_thickness_unverified',
        'scope':'Bridge/web/rib and present structural posts; mechanical stress not verified'}


def pole_slot_pairs(request):
    values=request.get('pole_slot_candidates',catalog()['policy']['default_pole_slot_pairs'])
    if not isinstance(values,list) or not values or len(values)>256:raise ValueError('Use 1..256 explicit pole/slot candidate pairs')
    output=[];seen=set()
    for value in values:
        if not isinstance(value,dict) or set(value)!={'poles','slots'}:raise ValueError('Pole/slot pair requires poles and slots only')
        p=_number(value['poles'],'poles',2);q=_number(value['slots'],'slots',3)
        if p!=int(p) or int(p)%2 or q!=int(q) or p>512 or q>512:raise ValueError('Poles must be an even integer 2..512; slots an integer 3..512')
        pair=(int(p),int(q))
        if pair in seen:raise ValueError('Duplicate pole/slot pair')
        seen.add(pair);output.append({'poles':pair[0],'slots':pair[1]})
    return output


def validate_parameters(options,manufacturing=None):
    rotor=resolve_rotor(options);params=options.get('parameters',{})
    if not isinstance(params,dict):raise ValueError('Rotor parameters must be an object')
    definitions=catalog()['parameter_definitions'];normalized={};warnings=[]
    for key,setting in params.items():
        match=re.fullmatch(r'L([1-9][0-9]*)\.(.+)',key)
        base=match[2] if match else key
        if base not in rotor['parameters']:raise ValueError('Parameter does not belong to '+rotor['label']+': '+key)
        if match and (not rotor['layered'] or base not in rotor['layer_parameters']):raise ValueError('Unexpected layer parameter: '+key)
        if rotor['layered'] and base in rotor['layer_parameters'] and not match:raise ValueError('Use a layer prefix such as L1.'+base)
        if not isinstance(setting,dict) or setting.get('mode','auto') not in ('auto','fixed','range'):raise ValueError('Invalid parameter mode: '+key)
        mode=setting.get('mode','auto');spec=definitions[base]
        allowed={'mode'} if mode=='auto' else {'mode','value'} if mode=='fixed' else {'mode','min','max'}
        if set(setting)-allowed:raise ValueError('Unexpected parameter fields: '+key)
        item={'mode':mode}
        values=[] if mode=='auto' else [('value',setting.get('value'))] if mode=='fixed' else [('min',setting.get('min')),('max',setting.get('max'))]
        for name,value in values:
            value=_number(value,key)
            if value<spec['minimum'] or (value==spec['minimum'] and not spec['minimum_inclusive']):raise ValueError('Parameter below domain: '+key)
            if spec['maximum'] is not None and value>spec['maximum']:raise ValueError('Parameter above domain: '+key)
            if spec['kind']=='integer' and value!=int(value):raise ValueError('Integer parameter required: '+key)
            if spec['unit']=='mm' and abs(value*10-round(value*10))>1e-7:raise ValueError('0.1 mm input grid required: '+key)
            item[name]=value
        if mode=='range' and item['min']>item['max']:raise ValueError('Parameter range reversed: '+key)
        threshold=(manufacturing or {}).get('effective_minimum_mm')
        if spec['structural_section'] and values:
            if threshold is None:warnings.append('Material thickness is needed to check '+key)
            else:
                for name,value in values:
                    if value==0 and spec['zero_means_absent']:continue
                    if value<threshold-1e-9:raise ValueError(f'{key} must be >= {threshold:g} mm (max of 0.5 mm and material thickness)')
        normalized[key]=item
    layer_setting=normalized.get('magnet_layers',{})
    for key in normalized:
        match=re.match(r'L([1-9][0-9]*)\.',key)
        if match and layer_setting.get('mode')=='fixed' and int(match[1])>layer_setting['value']:
            raise ValueError('Layer index exceeds fixed Magnet Layers: '+key)
    return {'rotor_id':rotor['id'],'parameters':normalized,'warnings':warnings}


def capabilities(rotor):
    models=[m for m in catalog()['reference_models'] if m['rotor_id']==rotor['id']]
    available=[m for m in models if (ROOT/m['relative_path']).is_file()]
    return {'registered':True,'input_mapping_verified':rotor['input_mapping_status']=='verified',
        'geometry_adapter_available':bool(rotor['geometry_adapter']),
        'formula_reference_directions':[m['magnetisation'] for m in available],
        'verification_directions':rotor['verification_ready_directions'],
        'detailed_parameter_optimizer_connected':False,'design_qualified':False}


def preflight(request):
    options=request.get('spm',{});rotor=resolve_rotor(options);rule=manufacturing_rule(request)
    params=validate_parameters(options,rule);pairs=pole_slot_pairs(request);caps=capabilities(rotor)
    if request.get('skew') is not None or request.get('skew_deg') is not None:raise ValueError('Skew is excluded from this program')
    direction=options.get('magnetisation',default_magnetisation(options))
    if direction not in ('Radial','Parallel','Template'):raise ValueError('Unknown magnetisation specification')
    reasons=[]
    if direction not in caps['formula_reference_directions']:reasons.append('Matching rotor/direction reference and performance model are not connected')
    if not caps['geometry_adapter_available']:reasons.append('Rotor-specific geometry adapter is not connected')
    reference=reference_model(options)
    if reference:
        for key in ('core','magnet','connection','strands','paths'):
            if key in request and request[key]!=reference[key]:reasons.append('Matching reference condition not connected: '+key)
        if request.get('temperatures_C') and request['temperatures_C'][0]!=reference['temperature_C']:
            reasons.append('Reference temperature is not connected')
    if rule['material_evidence'] and rule['lamination_thickness_mm'] is not None and abs(rule['lamination_thickness_mm']-rule['material_evidence']['value_mm'])>1e-9:
        reasons.append('Actual lamination thickness differs from the material record; matching loss/performance model required')
    active=[k for k,v in params['parameters'].items() if v['mode']!='auto']
    if active:reasons.append('Detailed parameters are registered but not optimized by the current five-variable engine: '+', '.join(active))
    if request.get('geometry_parameters'):
        from spm_geometry import validate_settings
        settings=validate_settings(request['geometry_parameters'])
        active_stator=[k for k,v in settings.items() if v['mode']!='auto']
        if active_stator:reasons.append('Detailed stator geometry parameters are not optimized by the current five-variable engine: '+', '.join(active_stator))
    pair_review=[]
    from controller_limits import pole_limit
    from winding_layout import synthesize
    speed=request.get('operating_point',{}).get('speed_rpm')
    for pair in pairs:
        known=pair=={'poles':4,'slots':12}
        winding=synthesize(pair['poles'],pair['slots'],2 if known else None)
        pwm=pole_limit(speed,request.get('switching_frequency_hz'),pair['poles']) if speed is not None else None
        pair_review.append({**pair,'slots_per_pole_per_phase':pair['slots']/(3*pair['poles']),
            'cogging_order_indicator':math.lcm(pair['poles'],pair['slots']),
            'existing_calibrated_template':known,'winding_qualified':False,
            'winding_analysis':winding,
            'electrical_frequency_Hz':pair['poles']*speed/120 if speed is not None else None,
            'pwm_check':pwm,'status':'existing_template' if known else 'winding_and_model_pending'})
        if not known:reasons.append(f"{pair['poles']} poles / {pair['slots']} slots: winding and performance model not connected")
        if not winding['balanced']:reasons.append(f"{pair['poles']} poles / {pair['slots']} slots: no balanced winding in the supported double-layer family")
        if pwm and not pwm['passes']:reasons.append(f"{pair['poles']} poles excluded: fewer than 20 PWM periods per electrical cycle")
    checks=[{'id':key,'state':'not_evaluated'} for key in rotor['constraint_ids']]
    return {'rotor_id':rotor['id'],'label':rotor['label'],'capabilities':caps,
        'manufacturing':rule,'parameters':params['parameters'],'warnings':params['warnings'],
        'pole_slot_review':pair_review,'skew_enabled':False,'constraint_states':checks,
        'executable':not reasons,'blocking_reasons':list(dict.fromkeys(reasons)),
        'scope':'Configuration/capability review only; no physical geometry, winding or performance qualification'}


def require_execution(request,kind='formula'):
    review=preflight(request)
    if not review['executable']:raise ValueError('; '.join(review['blocking_reasons']))
    if kind=='verification' and request.get('spm',{}).get('magnetisation',default_magnetisation(request.get('spm',{}))) not in review['capabilities']['verification_directions']:
        raise ValueError('Prescribed-current geometry verification is not connected for this rotor/direction')
    return review


def catalog_payload():
    result=copy.deepcopy(catalog())
    for rotor in result['rotors']:rotor['capabilities']=capabilities(rotor)
    return result
