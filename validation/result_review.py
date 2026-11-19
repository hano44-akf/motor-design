"""Read-only result presentation; historical flags are never qualification."""
from pathlib import Path
import math
from result_policy import requirement,summarize_requirements,candidate_rank
from run_assessment import assess_run,deficit_summary
from verification_conditions import coverage,capacity_partner

METRICS={
 'efficiency_pct':('효율','%', 'System Efficiency','efficiency_pct'),
 'resistance_ohm':('상저항','Ω','Phase Resistance','resistance_ohm'),
 'back_emf_phase_rms_V':('상 역기전력 기본파 RMS','V','Back EMF Line-Line Voltage (peak) (fundamental)','back_emf_phase_rms_V'),
 'ripple_pct':('토크 리플','%','Torque Ripple (MsVw) [%]',None)}


def review_result(result,folder):
    request=result['request'];op=request['operating_point'];folder=Path(folder)
    candidates=[]
    for c in result['results']:
        runs=[];assessments=[];deficits=[]
        saved=c.get('runs',[]);condition_coverage=coverage(saved,request)
        for original in c.get('runs',[]):
            a=assess_run(original,request,capacity_partner(original,saved,request))
            assessments.append(a);deficits.append(deficit_summary({**original,'assessment':a},request))
            requirements=[{'id':key,**detail,'evidence_only':key in ('iron_flux_density','nonlinear_control_optimality','demagnetization_under_negative_Id')} for key,detail in a['requirement_details'].items()]
            for key,input_key in [('efficiency_pct','efficiency_min_pct'),('current_density_max_A_mm2','current_density_max_A_mm2'),('dc_current_max_A','dc_current_max_A')]:
                if op.get(input_key) is None:requirements.append({'id':key,**requirement(None,None)})
            for item in requirements:
                if item['id']=='pwm_current_ripple':item['limit']=request.get('pwm_current_ripple_max_pct') or 15
            screens=[{'id':key,'state':'passed' if passed else 'unverified' if key.startswith('finite_') or key=='input_mapping_checked' else 'violated'} for key,passed in a['checks'].items()]
            metrics=[]
            temp=original.get('input_options',{}).get('temperature_C')
            same_condition=original.get('verification_role','nominal')=='nominal' and temp==request.get('temperatures_C',[None])[0] and original['design']['voltage_V']==min(op['voltages_V'])
            for key,(label,unit,native,predkey) in METRICS.items():
                actual=original['values'].get(native);predicted=c.get('prediction',{}).get(predkey) if predkey else None
                if key=='back_emf_phase_rms_V':
                    connection=original.get('readback',{}).get('WindingConnection')
                    actual=actual/math.sqrt(2 if connection==1 else 6) if isinstance(actual,(int,float)) and connection in (0,1) else None
                metrics.append({'id':key,'label':label,'unit':unit,'actual':actual,'prediction':predicted,
                    'difference':actual-predicted if same_condition and isinstance(actual,(int,float)) and isinstance(predicted,(int,float)) else None,
                    'comparison_scope':'nominal matching temperature and bus; FEA current may be retuned' if same_condition else 'conditions differ; no error comparison'})
            label=original.get('label','');model=folder/(label+'.mot')
            safe=model.resolve().parent==folder.resolve() and model.is_file()
            runs.append({'label':label,'temperature_C':temp,'voltage_V':original['design']['voltage_V'],
                'verification_role':original.get('verification_role','nominal'),
                'torque_Nm':original['values'].get('Shaft Torque'),'requirements':requirements,
                'requirement_summary':a['requirement_summary'],'physical_screens':screens,
                'physical_screens_pass':a['physical_screens_pass'],'target_met':a['target_met'],
                'metrics':metrics,'geometry_mm':original.get('geometry_mm',{}),'timings':original.get('timings',{}),
                'model_path':str(model.resolve()) if safe else None})
        if assessments:
            physical=all(a['physical_screens_pass'] for a in assessments)
            passed=condition_coverage['complete'] and all(a['target_met'] for a in assessments)
            rank=candidate_rank(assessments,deficits)
            if not condition_coverage['complete']:rank=(*rank[:2],rank[2]+len(condition_coverage['missing'])+len(condition_coverage['unexpected_or_duplicate']))
            status='requirements_passed' if passed else 'requirements_violated' if rank[0] else 'verification_incomplete'
            known=max(d['known_normalized_shortfall'] for d in deficits)
        else:
            physical=None;passed=False;status='verification_incomplete';known=None;rank=(False,0,1)
        candidates.append({'id':c['id'],'design':c['design'],'prediction':c.get('prediction',{}),'runs':runs,
            'condition_coverage':condition_coverage,
            'formula_review':c.get('formula_review'),
            'status':status,'target_met':passed,'physical_screens_pass':physical,
            'worst_known_normalized_shortfall':known,'rank':rank,
            'evidence':'formula_only' if not runs else 'saved_FEA_reassessed'})
    eligible=[c for c in candidates if c['physical_screens_pass'] is True]
    best=min(eligible,key=lambda c:(not c['target_met'],c['rank'])) if eligible else None
    diagnostic=min((c for c in candidates if c['runs']),key=lambda c:c['rank'],default=None)
    return {'schema':'result-review-v1','stage':result.get('stage'),'candidates':candidates,
        'best_available':best['id'] if best else None,'best_diagnostic':diagnostic['id'] if diagnostic and not eligible else None,
        'timings':result.get('timings',{}),'search_statistics':result.get('search_statistics',{}),
        'ranking_policy':'Physical screens must pass for best_available. Within requirement status, worst-condition known normalized deficit precedes missing count. Unknown is never zero evidence.',
        'scope':'Read-only reassessment of saved runs. Formula-only results remain unverified; neither manufacturing approval nor new FEA.',
        'motorcad_solves':0}
