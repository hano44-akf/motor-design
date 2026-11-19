"""Explicit nominal/capacity execution plan and saved evidence coverage."""
from collections import Counter


def condition_plan(request):
    op=request['operating_point'];margin=op.get('torque_margin_pct',0)
    return [dict(role=role,temperature_C=temp,voltage_V=bus,
                 target_torque_Nm=op['torque_Nm']*factor,
                 condition_id=f'{role}_t{ti}_v{vi}',temperature_index=ti,voltage_index=vi)
            for ti,temp in enumerate(request['temperatures_C'])
            for vi,bus in enumerate(op['voltages_V'])
            for role,factor in ([('nominal',1),('capacity',1+margin/100)] if margin>0 else [('nominal',1)])]


def run_key(run):
    return (run.get('verification_role','nominal'),run.get('input_options',{}).get('temperature_C'),
            run.get('design',{}).get('voltage_V'))


def coverage(runs,request):
    expected=Counter((p['role'],p['temperature_C'],p['voltage_V']) for p in condition_plan(request))
    actual=Counter(run_key(r) for r in runs)
    return {'complete':actual==expected,'missing':[list(k) for k in (expected-actual).elements()],
            'unexpected_or_duplicate':[list(k) for k in (actual-expected).elements()]}


def capacity_partner(run,runs,request):
    if run_key(run)[0]!='nominal' or request['operating_point'].get('torque_margin_pct',0)<=0:return None
    key=('capacity',*run_key(run)[1:]);matches=[r for r in runs if run_key(r)==key]
    if len(matches)!=1:return None
    partner=matches[0]
    fields=('diameter_mm','length_mm','turns_per_coil','wire_diameter_mm','airgap_mm','geometry_mm')
    if any(run.get('design',{}).get(k)!=partner.get('design',{}).get(k) for k in fields):return None
    if run.get('geometry_mm')!=partner.get('geometry_mm'):return None
    return partner
