"""Resolve overlapping UI settings without dropping or rounding fixed values."""
import math

DEFAULTS=(('Slot_Opening',1.,3.,'mm'),('Magnet_Arc_[ED]',40.,100.,'electrical degree'),('MagnetReduction',0.,1.5,'mm'))


def search_space(snapshot=None):
    s=snapshot or {};unit={'mm':1,'cm':10,'m':1000}.get(s.get('units','mm'))
    if unit is None:raise ValueError('Unsupported length unit')
    sources={k:[] for k,_,_,_ in DEFAULTS}
    def add(field,setting,source,factor=1):
        if not isinstance(setting,dict):raise ValueError(source+': dimension setting object required')
        mode=setting.get('mode','auto')
        if mode=='auto':return
        if mode not in ('fixed','range'):raise ValueError(source+': fixed/range mode required')
        values=[setting.get('value')]*2 if mode=='fixed' else [setting.get('min'),setting.get('max')]
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
            raise ValueError(source+': finite bounds/value required')
        lo,hi=[v*factor for v in values]
        if lo>hi:raise ValueError(source+': reversed bounds')
        if mode=='fixed' and not math.isclose(lo*10,round(lo*10),abs_tol=1e-7):
            raise ValueError(source+': fixed value must be on the 0.1 mm / 0.1 ED development grid')
        sources[field].append({'source':source,'mode':mode,'min':lo,'max':hi})
    geometry=s.get('geometry',{});modes=s.get('modes',{});ranges=s.get('ranges',{})
    for key,field,factor in (('slotOpening','Slot_Opening',unit),('poleArc','Magnet_Arc_[ED]',180)):
        mode=modes.get(key,'fixed' if geometry.get(key) not in (None,'') else 'auto')
        add(field,{'mode':mode,'value':geometry.get(key),**(ranges.get(key,{}) if mode=='range' else {})},'geometry.'+key,factor)
    stator=s.get('statorParameters',{})
    if 'slot_opening_mm' in stator:add('Slot_Opening',stator['slot_opening_mm'],'stator.slot_opening_mm')
    mappings={'pole_arc_ed':'Magnet_Arc_[ED]','magnet_reduction_mm':'MagnetReduction'}
    # Inactive rotor drafts are irrelevant; only the selected Breadloaf is read.
    drafts=s.get('rotorParameters',{}).get('surface_breadloaf',{})
    for origin,settings in (('rotor',drafts),('spm',s.get('spm',{}).get('parameters',{}))):
        for key,field in mappings.items():
            if key in settings:add(field,settings[key],origin+'.'+key)
    variables=[];bounds=[];combinations=1
    for field,default_lo,default_hi,unit_name in DEFAULTS:
        lo,hi=default_lo,default_hi
        for item in sources[field]:
            if item['min']<default_lo-1e-8 or item['max']>default_hi+1e-8:
                raise ValueError(item['source']+': outside supported development range '+str((default_lo,default_hi)))
            lo=max(lo,item['min']);hi=min(hi,item['max'])
        lower=math.ceil(lo*10-1e-8);upper=math.floor(hi*10+1e-8)
        if lower>upper:raise ValueError(field+': conflicting settings or no grid point in range')
        count=upper-lower+1;combinations*=count;bounds.append((lower,upper))
        variables.append({'id':field,'min':lower/10,'max':upper/10,'step':.1,'unit':unit_name,
                          'mode':'fixed' if lower==upper else 'range','grid_points':count,'sources':sources[field]})
    return {'variables':variables,'tick_bounds':bounds,'full_grid_combinations':combinations,
            'free_variable_count':sum(a!=b for a,b in bounds),'fixed_variable_count':sum(a==b for a,b in bounds),
            'merge_policy':'Intersect all explicit settings; reject conflicts; never round an off-grid fixed value.'}
