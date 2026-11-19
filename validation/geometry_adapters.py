"""Rotor geometry dispatch. Unknown templates never fall back to Surface Radial."""
import math
from dimension_grid import mm
from rotor_catalog import resolve_rotor


def _surface(d,l,overrides):
    scale=d/130
    recipe={'Housing_Dia':140,'Stator_Lam_Dia':130,'Stator_Bore':80,'Shaft_Dia':25,'Tooth_Width':10.5,
            'Slot_Depth':18,'Slot_Opening':3,'Tooth_Tip_Depth':1,'Magnet_Thickness':4,'Airgap':1}
    values={k:mm(v*scale) for k,v in recipe.items()}
    values.update({k:mm(l) for k in ('Stator_Lam_Length','Rotor_Lam_Length','Magnet_Length')})
    values.update({'Shaft_Dia_[F]':values['Shaft_Dia'],'Shaft_Dia_[R]':values['Shaft_Dia']})
    if set(overrides)-set(values):raise ValueError('Unmapped geometry inputs: '+', '.join(sorted(set(overrides)-set(values))))
    values.update(overrides)
    for key,value in values.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('Positive finite dimension required: '+key)
        if abs(value-mm(value))>1e-8:raise ValueError('Dimension must be on 0.1 mm grid: '+key)
    if not values['Shaft_Dia']<values['Stator_Bore']<values['Stator_Lam_Dia']<=values['Housing_Dia']:
        raise ValueError('Shaft/bore/stator/housing diameters interfere')
    if values['Slot_Depth']>=(values['Stator_Lam_Dia']-values['Stator_Bore'])/2:
        raise ValueError('Slot depth leaves no stator yoke')
    if values['Airgap']+values['Magnet_Thickness']>=(values['Stator_Bore']-values['Shaft_Dia'])/2:
        raise ValueError('Gap/magnet leaves no rotor iron between magnet and shaft')
    return values


ADAPTERS={'surface_proportional_v1':_surface}


def build_geometry(options,d,l,overrides=None):
    rotor=resolve_rotor(options);name=rotor['geometry_adapter']
    if name not in ADAPTERS:raise ValueError('Geometry adapter pending for '+rotor['label'])
    return ADAPTERS[name](d,l,overrides or {})
