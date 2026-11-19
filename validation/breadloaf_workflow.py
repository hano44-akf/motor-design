"""Staged Breadloaf development workflow, executable without an AI agent.

Native FEA starts ONLY via the explicit `start` command. Search/review/status
never start a native application or poll until FEA completion.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from study_io import write_json

ROOT=Path(__file__).resolve().parent


def status(folder):
    folder=Path(folder).resolve()
    progress=folder/'progress.json'
    return {'folder':str(folder), 'progress':json.loads(progress.read_text(encoding='utf-8')) if progress.exists() else {'status':'prepared_not_started'}}


def start(folder):
    folder=Path(folder).resolve()
    if (folder/'progress.json').exists() or (folder/'workflow_launch.json').exists():
        raise ValueError('Batch already started; inspect status rather than relaunch')
    plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    if not plan.get('cases') or any(c['rotor_id']!='surface_breadloaf' for c in plan['cases']):
        raise ValueError('Nonempty Breadloaf-only batch required; Flat deferred')
    with (folder/'stdout.log').open('wb') as stdout, (folder/'stderr.log').open('wb') as stderr:
        process=subprocess.Popen([sys.executable,str(ROOT/'run_spm_ripple_recovery.py'),'--output',str(folder)],
                                 cwd=ROOT.parent,stdout=stdout,stderr=stderr,
                                 creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    result={'supervisor_pid':process.pid,'folder':str(folder),'planned_fea':len(plan['cases']),
            'waited_for_completion':False,'estimated_duration_minutes':plan.get('estimated_duration_minutes')}
    write_json(folder/'workflow_launch.json',result)
    return result


def review(folder):
    from review_breadloaf_verification import review as review_native
    folder=Path(folder).resolve();plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
    if plan.get('source_search'):
        source=Path(plan['source_search'])/'result.json'
        if hashlib.sha256(source.read_bytes()).hexdigest()!=plan.get('source_search_result_sha256'):
            raise ValueError('Saved source search changed; comparison must use frozen predictions')
    report=review_native(folder)
    if plan.get('source_search'):
        from breadloaf_operating_comparison import compare
        compare(plan['source_search'],folder)
    if plan.get('request_contract'):
        from breadloaf_remaining_review import build
        build(folder)
    generation=plan.get('feedback_generation',1 if plan.get('schema')=='breadloaf-local-current-feedback-v1' else 0)
    maximum=plan.get('max_current_corrections',1)
    passed=bool(report['cases']) and all(r['requirement_summary']['passed'] for r in report['cases'])
    known_passed=bool(report['cases']) and all(r['requirement_summary']['known_requirements_passed'] for r in report['cases'])
    ripple_failed=any(r['requirements'].get('requested_ripple',r['requirements']['actual_ripple_20pct'])['state']=='violated'
                      for r in report['cases'])
    report['workflow']={'feedback_generation':generation,'max_current_corrections':maximum,
                        'automatic_extra_fea':False,
                        'strict_development_targets_passed':passed,
                        'next_action':'archive_selected_point_evidence' if passed else
                            'revise_geometry_for_ripple' if ripple_failed else
                            'resolve_remaining_verification' if known_passed else
                            'review_residual_correction_budget_exhausted' if generation>=maximum else
                            'prepare_optional_local_current_correction',
                        'policy':'Strict target shortfall remains visible even if numerically small; no automatic acceptance tolerance.'}
    feedback=plan.get('feedback')
    if feedback:
        source=Path(plan.get('feedback_source_folder',Path(plan['cases'][0]['source_folder']).parent))
        parent_id=feedback['parent_id'];prior=json.loads((source/'result.json').read_text(encoding='utf-8'))
        original=next(r for r in prior['outcomes'] if r['id']==parent_id)
        now=report['cases'][0]
        report['before_after']={'parent_id':parent_id,'corrected_id':now['id'],
            'before':{'line_peak_A':feedback['native_observation']['line_peak_A'],
                      'electromagnetic_torque_Nm':original['values']['Average torque (MsVw)'],
                      'shaft_torque_Nm':original['values'].get('Shaft Torque'),
                      'ripple_pct':original['actual_ripple_pct'],'efficiency_pct':original['values'].get('System Efficiency')},
            'after':{'line_peak_A':now['line_peak_A'],'electromagnetic_torque_Nm':now['mean_electromagnetic_torque_Nm'],
                     'shaft_torque_Nm':now['shaft_torque_Nm'],'ripple_pct':now['actual_ripple_pct'],'efficiency_pct':now['efficiency_pct']},
            'new_independent_geometry_cases':0}
    write_json(folder/'workflow_review.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('search');s.add_argument('--seed-snapshot',type=Path,required=True);s.add_argument('--output',type=Path,required=True)
    s.add_argument('--target-electromagnetic-torque',type=float,default=.5);s.add_argument('--max-line-peak-current',type=float,default=40)
    s.add_argument('--iterations',type=int,default=10)
    s=sub.add_parser('prepare');s.add_argument('--study',type=Path,required=True);s.add_argument('--model',type=Path,required=True);s.add_argument('--output',type=Path,required=True)
    for name in ('start','status','review'):
        s=sub.add_parser(name);s.add_argument('--batch',type=Path,required=True)
    s=sub.add_parser('feedback');s.add_argument('--batch',type=Path,required=True);s.add_argument('--output',type=Path,required=True);s.add_argument('--max-corrections',type=int,default=1)
    a=p.parse_args()
    if a.command=='search':
        from optimize_breadloaf_ripple import run
        r=run(a.seed_snapshot,a.output,a.target_electromagnetic_torque,a.max_line_peak_current,a.iterations)
        r={k:r[k] for k in ('elapsed_s','unique_candidates','finalists')}
    elif a.command=='prepare':
        from prepare_breadloaf_verification import prepare
        r=prepare(a.study,a.model,a.output)
    elif a.command=='feedback':
        from prepare_breadloaf_current_feedback import prepare
        r=prepare(a.batch,a.output,a.max_corrections)
    elif a.command=='start':r=start(a.batch)
    elif a.command=='review':r=review(a.batch)
    else:r=status(a.batch)
    print(json.dumps(r,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
