"""Parametric SPM envelope/section evaluator, independent of performance/FEA.

This registers detailed search variables but does not reuse the five-variable
performance surrogate for new shapes. Breadloaf corner geometry awaits native
template readback; reduction is never presented as verified corner thickness.
"""
import math
from dimension_grid import mm
from rotor_catalog import resolve_rotor,validate_parameters,manufacturing_rule,pole_slot_pairs
from verification_scope import POLICY

SUPPORTED={'surface_radial','surface_parallel','surface_breadloaf'}
STATOR_FIELDS={
 'stator_bore_mm':('스테이터 내경','Stator_Bore'),
 'shaft_diameter_mm':('축경','Shaft_Dia'),
 'tooth_width_mm':('치폭','Tooth_Width'),
 'slot_depth_mm':('슬롯 깊이','Slot_Depth'),
 'slot_opening_mm':('슬롯 입구 폭','Slot_Opening'),
 'tooth_tip_depth_mm':('치끝 두께','Tooth_Tip_Depth'),
 'housing_diameter_mm':('하우징 외경','Housing_Dia')}


def validate_settings(settings):
    if not isinstance(settings,dict):raise ValueError('geometry_parameters must be an object')
    normalized={}
    for key,value in settings.items():
        if key not in STATOR_FIELDS:raise ValueError('Unknown detailed stator dimension: '+key)
        if not isinstance(value,dict):raise ValueError('Dimension setting required: '+key)
        mode=value.get('mode','auto')
        allowed={'auto':{'mode'},'fixed':{'mode','value'},'range':{'mode','min','max'}}
        if mode not in allowed or set(value)-allowed[mode]:raise ValueError('Invalid dimension mode/fields: '+key)
        values=[] if mode=='auto' else [value.get('value')] if mode=='fixed' else [value.get('min'),value.get('max')]
        for v in values:
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:raise ValueError('Positive finite dimension required: '+key)
            if abs(v*10-round(v*10))>1e-7:raise ValueError('0.1 mm dimension grid required: '+key)
        if mode=='range' and values[0]>values[1]:raise ValueError('Reversed dimension range: '+key)
        normalized[key]={'mode':mode,**{k:v for k,v in value.items() if k!='mode'}}
    return normalized


def _point(setting,seed,length=True):
    mode=setting.get('mode','auto')
    value=seed if mode=='auto' else setting['value'] if mode=='fixed' else (setting['min']+setting['max'])/2
    return mm(value) if length else value


def preview(request):
    options=request.get('spm',{});rotor=resolve_rotor(options)
    if rotor['id'] not in SUPPORTED:raise ValueError('Detailed SPM geometry supports Radial / Parallel / Breadloaf only')
    settings=validate_settings(request.get('geometry_parameters',{}))
    rotor_settings=validate_parameters(options,manufacturing_rule(request))['parameters']
    seed=request.get('dimensions',{})
    if not isinstance(seed,dict):raise ValueError('Seed dimensions must be an object')
    d=seed.get('diameter_mm',85);length=seed.get('length_mm',20)
    for value in (d,length):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0 or abs(value*10-round(value*10))>1e-7:raise ValueError('Seed diameter/length must be positive on the 0.1 mm grid')
    gap_bounds=request.get('airgap_bounds_mm',[.4,.6])
    from operating_control import airgap_bounds
    gap_bounds=airgap_bounds({'airgap_bounds_mm':gap_bounds})
    designs=[]
    for pair in pole_slot_pairs(request):
        scale=d/130
        native={'Housing_Dia':mm(140*scale),'Stator_Lam_Dia':d,'Stator_Bore':mm(80*scale),
            'Shaft_Dia':mm(25*scale),'Tooth_Width':mm(10.5*scale*12/pair['slots']),
            'Slot_Depth':mm(18*scale),'Slot_Opening':mm(3*scale*12/pair['slots']),
            'Tooth_Tip_Depth':mm(scale),'Magnet_Thickness':mm(4*scale),'Airgap':mm(sum(gap_bounds)/2),
            'Stator_Lam_Length':length,'Rotor_Lam_Length':length,'Magnet_Length':length}
        search=[]
        for key,(_,field) in STATOR_FIELDS.items():
            setting=settings.get(key,{'mode':'auto'});native[field]=_point(setting,native[field])
            search.append({'id':key,'unit':'mm','step':.1,'setting':setting,'preview_value':native[field]})
        magnet=rotor_settings.get('magnet_thickness_mm',{'mode':'auto'})
        native['Magnet_Thickness']=_point(magnet,native['Magnet_Thickness'])
        arc_setting=rotor_settings.get('pole_arc_ed',{'mode':'auto'});arc=_point(arc_setting,120,False)
        # Range midpoint for integer segment count must remain an integer.
        segment_setting=rotor_settings.get('magnet_segments',{'mode':'auto'})
        segments=int(round(_point(segment_setting,1,False)))
        reduction_setting=rotor_settings.get('magnet_reduction_mm',{'mode':'auto'})
        reduction=_point(reduction_setting,0) if rotor['id']=='surface_breadloaf' else None
        for key,setting,value,unit,step in [('magnet_thickness_mm',magnet,native['Magnet_Thickness'],'mm',.1),
                ('pole_arc_ed',arc_setting,arc,'deg electrical',None),('magnet_segments',segment_setting,segments,'count',1)]:
            search.append({'id':key,'unit':unit,'step':step,'setting':setting,'preview_value':value})
        if reduction is not None:search.append({'id':'magnet_reduction_mm','unit':'mm','step':.1,'setting':reduction_setting,'preview_value':reduction})
        bore=native['Stator_Bore'];shaft=native['Shaft_Dia'];depth=native['Slot_Depth'];mag=native['Magnet_Thickness'];gap=native['Airgap']
        yoke=(d-bore)/2-depth;rotor_outer=bore-2*gap;rotor_iron=rotor_outer-2*mag
        pitch=math.pi*bore/pair['slots']
        checks={'diameter_order':shaft<bore<d<=native['Housing_Dia'],
            'positive_yoke':yoke>0,'tooth_and_opening_fit_pitch':native['Tooth_Width']+native['Slot_Opening']<pitch,
            'tip_below_slot_depth':native['Tooth_Tip_Depth']<depth,
            'rotor_iron_outside_shaft':rotor_iron>shaft,'pole_arc_domain':0<arc<=180,
            'positive_dimensions':all(v>0 for v in native.values())}
        if reduction is not None:checks['reduction_below_center_thickness']=0<=reduction<mag
        # A necessary section/envelope screen, not an exact slot-area or full
        # circle intersection model. No B/ripple/efficiency is invented here.
        derived={'stator_yoke_thickness_mm':yoke,'bore_slot_pitch_mm':pitch,'rotor_outer_diameter_mm':rotor_outer,
            'rotor_iron_diameter_mm':rotor_iron,'pole_arc_mechanical_deg':arc/(pair['poles']/2),
            'magnet_edge_thickness_mm':None if reduction is not None else mag}
        designs.append({'pair':pair,'native_dimension_candidates':native,'magnet_arc_ed':arc,'magnet_segments':segments,
            'breadloaf_reduction_mm':reduction,'derived_geometry':derived,'checks':checks,
            'violations':[key for key,passed in checks.items() if not passed],
            'envelope_checks_passed':all(checks.values()),'search_parameters':search,
            'range_parameters':sum(v['setting']['mode']=='range' for v in search),
            'full_geometry_qualified':False,'performance_model_connected':False,
            'native_mapping_pending':['magnet_segments']+(['magnet_reduction_mm','breadloaf_corner_geometry'] if reduction is not None else []),
            'scope':'Representative midpoint only. A passing midpoint does not qualify the whole requested range. Derived dimensions retain precision; independent length inputs use 0.1 mm.'})
    return {'schema':'spm-detailed-geometry-preview-v1','rotor_id':rotor['id'],'seed_dimensions_mm':{'diameter_mm':d,'length_mm':length},
        'designs':designs,'verification_policy':POLICY,'optimization_connected':False,
        'limitations':['No magnetic saturation, torque ripple, loss or efficiency prediction.',
            'Breadloaf reduction is a template parameter; exact corner geometry is pending native readback.',
            'Existing five-variable formula optimizer rejects active detailed parameters.']}
