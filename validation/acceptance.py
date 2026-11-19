"""AI-independent fail-closed checks for this prescribed sinusoidal-current study.

Peak terminal voltage <= DC bus is a necessary waveform feasibility screen,
not a substitute for inverter/circuit simulation or a sufficient feasibility proof.
No torque-ripple threshold was requested; expose it as a review item.
"""
import math

def assess(result, efficiency_target=88.0):
    values=result.get('values',{})
    design=result.get('design',{})
    readback=result.get('readback',{})
    checks={}
    def number(source,key):
        value=source.get(key)
        return value if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) else None
    def minimum(key,limit):
        value=number(values,key)
        checks[key]=value is not None and value>=limit
    minimum('Shaft Torque',.5)
    minimum('System Efficiency',efficiency_target)
    efficiency=number(values,'System Efficiency')
    checks['efficiency_physical_range']=efficiency is not None and efficiency<=100
    bus=number(design,'voltage_V'); peak=number(values,'Line-Line Terminal Voltage (peak)')
    checks['peak_voltage_within_bus']=bus is not None and bus>0 and peak is not None and 0<=peak<=bus
    speed=number(values,'Shaft Speed')
    checks['speed_3500_rpm']=speed is not None and abs(speed-3500)<1e-6
    checks['solver_voltage_flag_clear']=result.get('voltage_limit_exceeded') is False
    for key,target in [('NumberStrandsHand',1),('ParallelPaths',1),('WindingConnection',1)]:
        checks[key]=number(readback,key)==target
    requested_wire=number(design,'wire_diameter_mm'); actual_wire=number(readback,'Copper_Diameter')
    checks['wire_applied']=requested_wire is not None and actual_wire is not None and abs(requested_wire-actual_wire)<1e-6
    checks['bus_applied']=bus is not None and number(readback,'DCBusVoltage')==bus and number(values,'DC Bus Voltage')==bus
    return dict(passed=all(checks.values()),checks=checks,failures=[k for k,ok in checks.items() if not ok],torque_ripple_pct=values.get('Torque Ripple (MsVw) [%]'),scope='Numerical result screens only; material provenance, thermal/manufacturing limits and inverter waveform validation remain separate.')
