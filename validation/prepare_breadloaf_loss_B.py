"""Frozen first loss/B development and holdout batch; no fitting or FEA here."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sqlite3

from optimize_breadloaf_ripple import make_snapshot
from spm_ripple import predict
from study_io import write_json

ROOT=Path(__file__).resolve().parent.parent


def material_audit():
    db=ROOT/'material_library/normalized_20261020/materials_si.sqlite';rows=[]
    with sqlite3.connect(db) as connection:
        for mid,name in connection.execute("SELECT id,name FROM materials WHERE name=?",('POSCO | 50PN470',)).fetchall():
            frequencies=[float(v[0]) for v in connection.execute("SELECT DISTINCT si_value_decimal FROM fields WHERE material_id=? AND base_key='Frequency'",(mid,)).fetchall()]
            rows.append({'id':mid,'name':name,'loss_frequencies_Hz':sorted(set(frequencies))})
    return {'database':str(db),'records':rows,'status':'Stored curves structurally normalized, not high-frequency loss validation',
            'nominal_operating_frequency_Hz':3500*4/120,
            'policy':'Do not call extrapolation beyond stored frequencies measured high-frequency material data.'}


def prepare(output):
    output=Path(output).resolve()
    if output.exists():raise ValueError('Fresh batch folder required')
    pilot=ROOT/'outputs/spm_ripple_validation_v2_20261103_140824'
    base=json.loads((ROOT/'outputs/spm_ripple_recovery_20261103/surface_breadloaf_13_snapshot.json').read_text(encoding='utf-8'))
    feedback=ROOT/'outputs/breadloaf_current_feedback_20261104'
    current_name='breadloaf_search_11_615_2_current1'
    current=json.loads((feedback/(current_name+'_snapshot.json')).read_text(encoding='utf-8'))
    # Main effects at fixed current; holdouts frozen separately, not training.
    definitions=[('D1','development',[10,550,0]),('D2','development',[30,550,4]),
                 ('D3','development',[10,850,1]),('D4','development',[30,800,4]),
                 ('H1','shape_holdout',[16,670,2]),('H2','shape_holdout',[24,760,3]),
                 ('S1','speed_check',1750),('S2','speed_check',7000)]
    output.mkdir(parents=True);cases=[]
    for suffix,role,setting in definitions:
        if role=='speed_check':
            s=copy.deepcopy(current);s['expected_native']['ShaftSpeed']=setting
            source=feedback/current_name;model=source/(current_name+'.mot')
        else:
            s=make_snapshot(base,setting);source=pilot;model=source/'surface_breadloaf_13.mot'
            s['line_peak_A']=40;s['expected_native']['PeakCurrent']=40
        name='breadloaf_loss_B_'+suffix;s['id']=name
        if not model.is_file() or not (source/'working_materials.mdb').is_file():raise ValueError('Native seed/database missing')
        raw=predict(s,2880,480)
        write_json(output/(name+'_snapshot.json'),s);write_json(output/(name+'_proxy.json'),raw)
        cases.append({'id':name,'rotor_id':'surface_breadloaf','role':role,
            'source_folder':str(source),'source_model_name':model.name,
            'source_model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
            'snapshot_sha256':hashlib.sha256((output/(name+'_snapshot.json')).read_bytes()).hexdigest(),
            'prediction_sha256':hashlib.sha256((output/(name+'_proxy.json')).read_bytes()).hexdigest(),
            'predicted_ripple_pct':raw['ripple_pct'],
            'operating_frequency_Hz':s['expected_native']['ShaftSpeed']*s['poles']/120})
    plan={'schema':'breadloaf-loss-B-development-v1','cases':cases,'planned_fea':8,
          'roles':{'development':4,'shape_holdout':2,'speed_check':2},
          'per_case_timeout_s':600,'estimated_duration_minutes':[16,28],
          'existing_reused_cases':6,'additional_required_fea_first_batch':8,
          'remaining_after_successful_execution':0,'remaining_count_scope':'Scheduled first batch only, not all future model qualification.',
          'production_model_connected':False,
          'scope':'Breadloaf loss/B development at fixed 4p12s/20C winding. Independent holdouts stay excluded from fitting. Flat deferred.',
          'metrics':['tooth/tooth-tip/stator-yoke/rotor-yoke maximum B','stator/rotor/magnet losses','hysteresis/eddy components',
                     'mean electromagnetic and shaft torque','efficiency','fundamental phasor voltage','ripple'],
          'policy':['Do not use H1/H2 in fitting before reporting first held-out results.',
                    'Speed checks are 58.33/233.33Hz; material tables do not establish full frequency accuracy.',
                    '7000rpm may exceed the 9V drive limit; record the flag, never call a diagnostic point a feasible motor design.',
                    '8 is an initial scoped evidence budget, not a promise that additional FEA will never be needed.',
                    'No thermal/structural/skew analyses. Manufacturing is not certified.']}
    write_json(output/'material_audit.json',material_audit());write_json(output/'plan.json',plan)
    return plan


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=prepare(a.output);print(json.dumps({'planned_fea':r['planned_fea'],'roles':r['roles'],'estimated_minutes':r['estimated_duration_minutes']}))
