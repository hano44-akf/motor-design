"""Explicit Motor-CAD v261 SPM inputs, checked by readback before solving.

BPMRotor order was read from the installed radial-flux rotor selector;
see automation/rotor_enum_evidence.json. Magnetization: official automation FAQ.
"""
import math
from rotor_catalog import catalog,resolve_rotor,validate_parameters,default_magnetisation

ROTOR_TYPES={r['input_value']:r['motorcad_rotor_value'] for r in catalog()['rotors'] if r['input_mapping_status']=='verified'}
MAGNETISATION={'Parallel':0,'Radial':1}
TEMPERATURE_KEYS=['Magnet_Temperature','StatorConductor_Temperature','StatorLam_Temperature','RotorLam_Temperature']

def variables(options):
    rotor=resolve_rotor(options)
    direction=options.get('magnetisation',default_magnetisation(options))
    validate_parameters(options)
    if any(s.get('mode','auto')!='auto' for s in options.get('parameters',{}).values()):
        raise ValueError('Detailed rotor parameter mapping is not connected; values cannot be silently ignored')
    if rotor['input_mapping_status']!='verified' or direction not in rotor['verified_magnetisation']:
        raise ValueError('Motor-CAD input mapping pending for '+rotor['label']+' / '+direction)
    settings={'BPMRotor':rotor['motorcad_rotor_value'],'Magnetization':MAGNETISATION[direction],
              'ShaftSpeed':options.get('speed_rpm',3500),
              'WindingConnection':{'delta':1,'star':0}[options.get('connection','delta')],
              'NumberStrandsHand':options.get('strands',1),'ParallelPaths':options.get('paths',1),
              'Magnet_Arc_[ED]':options.get('magnet_arc_deg',120)}
    if 'phase_advance_deg' in options:
        angle=options['phase_advance_deg']
        if isinstance(angle,bool) or not isinstance(angle,(int,float)) or not math.isfinite(angle) or not -89.9<=angle<=89.9:
            raise ValueError('Phase advance must be -89.9..89.9 electrical degrees')
        settings['PhaseAdvance']=angle
    settings.update({k:options.get('temperature_C',20) for k in TEMPERATURE_KEYS})
    for key,value in settings.items():
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
            raise ValueError('Invalid numeric setting: '+key)
    return settings

def apply_checked(mc, options):
    expected=variables(options)
    for key,value in expected.items():
        mc.set_variable(key,value)
    actual={key:mc.get_variable(key) for key in expected}
    for key,value in expected.items():
        if not isinstance(actual[key],(int,float)) or not math.isfinite(actual[key]) or abs(actual[key]-value)>1e-7:
            raise RuntimeError(f'Motor-CAD readback mismatch {key}: requested={value}, actual={actual[key]}')
    return actual
