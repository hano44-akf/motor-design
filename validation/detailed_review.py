"""Budget-limited FEA shape review, not a globally trained shape surrogate."""
import json
import time
from dimension_grid import mm


def refine(candidates,request,folder,calculate,progress,shortfall):
    began=time.perf_counter();op=request['operating_point'];bus=min(op['voltages_V']);temp=request['temperatures_C'][0]
    def rank(run):
        a=run['assessment']
        return (not a['physical_screens_pass'],not a['known_targets_met'],shortfall(run,request),-run['values']['System Efficiency'])
    for c in candidates:
        baseline=json.loads((folder/(c['tune_label']+'.json')).read_text(encoding='utf-8'))
        best=baseline;history=[];g=baseline['geometry_mm']
        # Design-directed samples; not a 0.1 mm exhaustive sweep.
        # Reduce slot depth to thicken the yoke; expose tooth width and magnet arc.
        for index,(depth_factor,tooth_factor,arc) in enumerate(((.85,1.,120),(.85,1.05,105),(.75,1.,90))):
            progress('detailed_shape_review',model=c['id'],trial=index+1)
            geometry={**c['design'].get('geometry_mm',{}),'Slot_Depth':mm(g['Slot_Depth']*depth_factor),
                      'Tooth_Width':mm(g['Tooth_Width']*tooth_factor)}
            d={**c['design'],'geometry_mm':geometry,'magnet_arc_deg':arc,
               'input_peak_current_A':baseline['design']['input_peak_current_A']*120/arc}
            trials=[]
            for correction in range(2):
                run=calculate(f"{c['id']}_detail{index}_tune{correction}",d,bus,temp,60)
                trials.append(run);torque=run['values']['Shaft Torque']
                if not run['assessment']['physical_screens_pass'] or op['torque_Nm']<=torque<=op['torque_Nm']*1.02:break
                d={**d,'input_peak_current_A':d['input_peak_current_A']*min(1.3,max(.7,op['torque_Nm']*1.005/max(torque,.001)))}
            # Do not reward overproduction via an artificially larger ripple denominator.
            matched=[r for r in trials if abs(r['values']['Shaft Torque']/op['torque_Nm']-1)<=.02]
            chosen=min(matched or trials,key=rank)
            history.append({'label':chosen['label'],'design':chosen['design'],
                            'shortfall':shortfall(chosen,request),'assessment':chosen['assessment']})
            if rank(chosen)<rank(best):best=chosen
        c['pre_detail_design']=baseline['design'];c['pre_detail_label']=baseline['label']
        c['detailed_review_trials']=history;c['design']=best['design'];c['tune_label']=best['label']
        # Keep the cheap prediction visibly tied to its original geometry.
        c['prediction_scope']='Initial proportional geometry only; no recalibrated detailed-shape prediction'
    (folder/'detailed_review.json').write_text(json.dumps({'wall_s':time.perf_counter()-began,
        'method':'Three directed shape alternatives per initial candidate, up to two current corrections; budget-limited FEA review, not exhaustive shape optimization',
        'candidates':[{'id':c['id'],'selected':c['tune_label'],'trials':c['detailed_review_trials']} for c in candidates]},indent=2),encoding='utf-8')
