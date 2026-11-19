"""Select independently verified continuous packing under the user's policy.

No optimisation or Native call. Records a geometric proposal, not an electrical
coil assignment, end path, modified Native model, or manufacturing approval.
"""
import argparse
import hashlib
import json
from pathlib import Path
from breadloaf_slot_detail import fields,dimensions
from breadloaf_continuous_packing import verify_native_boundary
from dimension_grid import resolution_policy
from study_io import write_json


def select(direct,persist=True):
    direct=Path(direct).resolve();load=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    path=direct/'continuous_packing_review.json';source=load(path)
    if not source.get('source_files') or any(not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest for p,digest in source['source_files'].items()):
        raise ValueError('Continuous packing original sources changed')
    plan=load(direct/'plan.json');mot=Path(plan['source_model']);geom=mot.parent/'native_geometry.json'
    if plan['candidate_id']!=source['candidate_id']:raise ValueError('Packing/source candidate mismatch')
    d=dimensions(fields(mot));points=source['best']['points_radial_tangential_mm']
    if len(points)!=source['target_wires']:raise ValueError('Packing wire count mismatch')
    check=verify_native_boundary(points,load(geom)['regions']['Impreg_1'],d['beta'],source['wire_outer_diameter_mm'],source['conductor_gap_mm'],source['wall_clearance_mm'])
    if not check['geometrically_verified']:raise ValueError('Independent packing boundary check failed')
    report={'schema':'breadloaf-selected-continuous-packing-v1','candidate_id':source['candidate_id'],
            'resolution_policy':resolution_policy(),'selection_status':'geometric_proposal_selected',
            'required_wires_per_slot':source['target_wires'],'points_radial_tangential_mm':points,
            'coordinates_rounded':False,'geometric_check':check,'whole_grid_diagnostic_required':False,
            'electrical_assignment_confirmed':False,'end_path_verified':False,'conductor_derived_end_area_mm2':None,
            'native_winding_updated':False,'performance_reverified_for_new_packing':False,'manufacturing_qualified':False,
            'qualified':False,'new_native_fea':0,
            'pending_checks':['coil/phase-to-coordinate assignment','end-turn routing and cuboid generation',
                              'manufacturing tolerances and winding-process review','performance effects of assigned/routed winding'],
            'source_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (path,mot,geom)},
            'scope':'Selected continuous geometric proposal in the existing cavity. Fixed design dimensions retain their 0.1mm input grid. Historical coordinate-grid search is optional evidence only.'}
    if persist:write_json(direct/'selected_continuous_packing.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--direct',required=True);a=p.parse_args();r=select(a.direct)
    print(json.dumps({k:v for k,v in r.items() if k not in ('source_files','points_radial_tangential_mm')},indent=2))
