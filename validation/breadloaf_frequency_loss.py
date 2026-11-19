"""Same-geometry/current frequency-loss diagnostic anchored to native components.

No geometry generalization, saturation, PWM loss or full frequency qualification.
"""
import math


def predict(values, speed_rpm):
    if not math.isfinite(speed_rpm) or speed_rpm<=0:raise ValueError('Positive speed required')
    base=values['Shaft Speed']
    if base<=0:raise ValueError('Positive reference speed required')
    ratio=speed_rpm/base;parts={}
    for key in ('Magnet Loss (on load)','Armature DC Copper Loss (on load)','Average torque (MsVw)'):
        if not math.isfinite(values[key]) or values[key]<0:raise ValueError('Finite nonnegative native losses/torque required')
    for region in ('Stator back iron','Stator tooth','Rotor back iron'):
        hysteresis=values[region+' Loss [hysteresis] (on load)']
        eddy=values[region+' Loss [eddy] (on load)']
        excess=values.get(region+' Loss [excess] (on load)',0)
        if any(not math.isfinite(x) or x<0 for x in (hysteresis,eddy,excess)):raise ValueError('Finite nonnegative loss components required')
        if excess>1e-9:raise ValueError('Nonzero excess loss needs a separately validated frequency law')
        parts[region]=hysteresis*ratio+eddy*ratio**2
    magnet=values['Magnet Loss (on load)']*ratio**2
    if values.get('Windage Loss (user input)',0)!=0 or values.get('Friction Loss (user input)',0)!=0:
        raise ValueError('Mechanical frequency-loss model not supported')
    copper=values['Armature DC Copper Loss (on load)']
    other=sum(parts.values())+magnet
    pem=values['Average torque (MsVw)']*2*math.pi*speed_rpm/60
    output=pem-other;input_power=pem+copper
    return {'speed_rpm':speed_rpm,'frequency_ratio':ratio,'iron_loss_components_W':parts,
        'magnet_loss_W':magnet,'copper_loss_W':copper,'shaft_output_power_W':output,
        'shaft_torque_Nm':output/(2*math.pi*speed_rpm/60),
        'efficiency_pct':100*output/input_power if input_power>0 and output>=0 else None,
        'qualified':False,'geometry_transfer_supported':False,
        'assumptions':['Same geometry, current, phase and temperatures as native reference.',
                       'Fixed-flux hysteresis proportional to frequency, eddy/magnet losses proportional to frequency squared.',
                       'Mean electromagnetic torque held constant. Frequency-dependent flux/skin/minor-loop changes not solved.',
                       'Native components are rounded; component sum may not equal reported total exactly.']}
