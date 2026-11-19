"""Local native-calibrated loss/B model. Held-out rows NEVER enter fit/CV.

Four input coordinates, log residual/response ridge regression. This is an
experimental local surrogate, not a new first-principles peak-field solver.
"""
import json
import math
from pathlib import Path
import numpy as np
from scipy.spatial import Delaunay, QhullError
from study_io import write_json

ROOT=Path(__file__).resolve().parent.parent
FEATURES=('Slot_Opening','Magnet_Arc_[ED]','MagnetReduction','PeakCurrent')
CENTER=np.array([2.,70.,.4,38.]);SCALE=np.array([1.,20.,.4,5.])
TARGETS=('Stator Tooth Flux Density (maximum)','Stator Tooth Tip Flux Density (maximum)',
    'Stator Back Iron Flux Density (maximum)','Rotor Back Iron Flux Density (maximum)',
    'Stator iron Loss [total] (on load)','Rotor iron Loss [total] (on load)',
    'Magnet Loss (on load)','Average torque (MsVw)')


def coordinates(row):return (np.array([row['features'][k] for k in FEATURES],dtype=float)-CENTER)/SCALE


def bases(row):
    return np.array([row['raw_tooth_section_B_T']]*2+[row['raw_yoke_section_B_T']]*2+[1.]*3+
                    [row['raw_mean_electromagnetic_torque_Nm']])


def design(x):return np.column_stack([np.ones(len(x)),x])


def coefficients(x,y,regularization):
    a=design(x);penalty=np.diag([0.]+[regularization]*4)
    return np.linalg.solve(a.T@a+penalty,a.T@y)


def fit(rows):
    # Filtering happens before coordinates, target transforms and CV.
    train=[r for r in rows if r.get('training_allowed') and r['features']['ShaftSpeed']==3500]
    if len(train)<8:raise ValueError('At least eight development points at 3500rpm required')
    x=np.array([coordinates(r) for r in train]);native=np.array([[r['native'][k] for k in TARGETS] for r in train],dtype=float)
    base=np.array([bases(r) for r in train])
    if not np.all(np.isfinite(native)) or np.any(native<=0) or np.any(base<=0):raise ValueError('Positive finite native metrics and raw bases required')
    y=np.log(native/base);scores=[]
    for regularization in (1e-4,.001,.01,.1,1.,10.):
        residual=[]
        for i in range(len(train)):
            keep=np.arange(len(train))!=i;c=coefficients(x[keep],y[keep],regularization)
            residual.append(design(x[i:i+1])@c-y[i:i+1])
        scores.append((float(np.mean(np.array(residual)**2)),regularization))
    cv,regularization=min(scores);c=coefficients(x,y,regularization)
    loo=[]
    for i in range(len(train)):
        keep=np.arange(len(train))!=i;estimate=base[i]*np.exp((design(x[i:i+1])@coefficients(x[keep],y[keep],regularization))[0])
        loo.append(estimate-native[i])
    return {'schema':'breadloaf-local-loss-B-ridge-v1','training_ids':[r['id'] for r in train],
        'excluded_ids':[r['id'] for r in rows if r not in train],
        'features':list(FEATURES),'targets':list(TARGETS),'coefficients':c.tolist(),
        'regularization':regularization,'training_only_loo_log_mse':cv,
        'observed_loo_max_abs_error':dict(zip(TARGETS,np.max(np.abs(loo),axis=0).tolist())),
        'training_coordinates':x.tolist(),'reference_speed_rpm':3500,'qualified':False,
        'domain_policy':'Four-dimensional convex hull of development coordinates. Outside hull is unverified.',
        'uncertainty_policy':'LOO residual maxima are empirical diagnostics, not guaranteed or statistical bounds.'}


def predict(model,row,allow_extrapolation=False):
    if row['features'].get('ShaftSpeed')!=model['reference_speed_rpm']:
        return {'available':False,'reason':'Local shape model is at 3500rpm; frequency transfer is not connected','qualified':False}
    x=coordinates(row)
    try:inside=bool(Delaunay(np.array(model['training_coordinates'])).find_simplex(x,tol=1e-8)>=0)
    except QhullError:return {'available':False,'reason':'Development domain is rank-deficient','qualified':False}
    if not inside and not allow_extrapolation:return {'available':False,'reason':'Outside local development convex hull','qualified':False}
    values=bases(row)*np.exp((design(x[None,:])@np.array(model['coefficients']))[0])
    return {'available':True,'inside_development_hull':inside,'values':dict(zip(TARGETS,values.tolist())),
            'qualified':False,'scope':'3500rpm local surrogate; extrapolation diagnostic only' if not inside else 'Local experimental estimate, FEA required'}


def operating_estimate(model,snapshot,line_peak_A,raw_mean_torque_Nm,tooth_B,yoke_B,copper_W):
    row={'features':{**snapshot['expected_native'],'PeakCurrent':line_peak_A},
         'raw_tooth_section_B_T':tooth_B,'raw_yoke_section_B_T':yoke_B,
         'raw_mean_electromagnetic_torque_Nm':raw_mean_torque_Nm}
    p=predict(model,row)
    if not p['available']:return p
    values=p['values'];omega=2*math.pi*snapshot['expected_native']['ShaftSpeed']/60
    other=sum(values[k] for k in TARGETS[4:7]);pem=values[TARGETS[7]]*omega
    output=pem-other;input_power=pem+copper_W
    return {**p,'other_losses_W':other,'shaft_torque_Nm':output/omega,
            'efficiency_pct':100*output/input_power if output>=0 and input_power>0 else None,
            'observed_loo_max_abs_error':model['observed_loo_max_abs_error'],
            'training_ids':model['training_ids'],'local_peak_B_estimate_T':max(values[k] for k in TARGETS[:4])}


def run(batch):
    batch=Path(batch).resolve();data=json.loads((batch/'paired_dataset.json').read_text(encoding='utf-8'));model=fit(data['rows'])
    comparisons=[]
    for row in data['rows']:
        if row['role']!='shape_holdout':continue
        result=predict(model,row,allow_extrapolation=True)
        differences={key:result['values'][key]-row['native'][key] for key in TARGETS}
        current=row['features']['PeakCurrent'];ref=json.loads((ROOT/'outputs/breadloaf_current_feedback_20261104/result.json').read_text(encoding='utf-8'))['outcomes'][0]['values']
        copper=.5*ref['Phase Resistance']*current**2;omega=2*math.pi*3500/60
        pem=result['values'][TARGETS[7]]*omega;other=sum(result['values'][k] for k in TARGETS[4:7])
        eta=100*(pem-other)/(pem+copper)
        comparisons.append({'id':row['id'],'inside_development_hull':result['inside_development_hull'],
            'prediction':result['values'],'native':row['native'],'differences':differences,
            'stator_iron_relative_error_pct':100*differences[TARGETS[4]]/row['native'][TARGETS[4]],
            'predicted_efficiency_pct':eta,'efficiency_error_percentage_points':eta-row['native']['System Efficiency'],
            'predicted_shaft_torque_Nm':(pem-other)/omega,'qualified':False})
    report={'schema':'breadloaf-local-loss-B-review-v1','model':model,'heldout_comparisons':comparisons,
        'new_fea_calls':0,'remaining_required_first_batch':data['counts']['remaining_required_first_batch'],
        'additional_fea_scheduled':0,'qualification':'Not family-wide validated. Two frozen shape checks only.',
        'training_includes_holdouts':False}
    write_json(batch/'local_loss_B_model.json',model);write_json(batch/'local_loss_B_review.json',report)
    return report


if __name__=='__main__':
    report=run(ROOT/'outputs/breadloaf_loss_B_validation_20261104')
    print(json.dumps({'training_ids':report['model']['training_ids'],'regularization':report['model']['regularization'],
        'heldout':[{'id':r['id'],'inside_hull':r['inside_development_hull'],'B_errors_T':{k:r['differences'][k] for k in TARGETS[:4]},
                    'iron_loss_error_pct':r['stator_iron_relative_error_pct']} for r in report['heldout_comparisons']]},indent=2))
