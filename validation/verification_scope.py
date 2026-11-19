"""Current user-defined verification scope; historical evidence stays immutable."""
import copy
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
CURRENT_CHECKLIST=ROOT/'outputs/verification_plan_current/validation_queue.json'
POLICY={'schema':'motor-verification-scope-v1','date':'2026-10-27',
        'excluded':['thermal_analysis','structural_stress_analysis'],
        'retained':['electromagnetic_performance','demagnetization','geometry_manufacturing_limits'],
        'temperature_policy':'Prescribed component temperatures remain inputs; no thermal equilibrium solve.',
        'manufacturing_policy':'Minimum bridge/web/rib dimensions retained; no mechanical stress analysis.'}


def current_checklist_path():
    return CURRENT_CHECKLIST if CURRENT_CHECKLIST.is_file() else ROOT/'outputs/topology_optimization_20261027/validation_queue.json'


def apply_scope(data):
    result=copy.deepcopy(data);tasks=[];renamed={};removed=set()
    for task in result['tasks']:
        if task['id'].endswith('_safety'):
            old=task['id'];new=old[:-7]+'_demagnetization';renamed[old]=new
            task.update(id=new,title='감자 검증',method='Motor-CAD electromagnetic / supported demagnetization solver',
                required_outputs=['demagnetization margin at specified magnet temperature and negative Id'],
                note='Prescribed temperatures and current limits required; thermal and structural analyses excluded by user.',
                depends_on=task.get('depends_on',[]))
        elif task.get('verification_domain') in ('thermal_analysis','structural_stress_analysis'):
            removed.add(task['id']);continue
        tasks.append(task)
    for task in tasks:task['depends_on']=[renamed.get(key,key) for key in task.get('depends_on',[]) if key not in removed]
    result['tasks']=tasks;result['verification_policy']=copy.deepcopy(POLICY)
    result['scope']='Electromagnetic checks and demagnetization. Thermal and structural analysis excluded.'
    return result
