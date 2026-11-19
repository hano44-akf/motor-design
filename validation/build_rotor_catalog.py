"""Build the shared catalog from installed menu evidence and explicit metadata.

Menu order is NOT treated as a verified SDK enum for the 13 unprobed types.
No Motor-CAD process is started by this module.
"""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parent.parent
BASE='https://ansyshelp.ansys.com/public/Views/Secured/MotorCAD/v252/en/Motor-CAD_UG/MotorCAD/topics/'


def build():
    fields={}
    def field(key,label,unit='mm',minimum=0,inclusive=False,maximum=None,structural=False,absent=False,scope='rotor'):
        fields[key]={'id':key,'label':label,'unit':unit,'kind':'integer' if unit=='count' else 'number',
            'minimum':minimum,'minimum_inclusive':inclusive,'maximum':maximum,
            'step':.1 if unit=='mm' else 1 if unit=='count' else None,
            'structural_section':structural,'zero_means_absent':absent,'scope':scope,
            'motorcad_variable':None,'mapping_status':'pending','optimizer_connected':False}
    field('magnet_thickness_mm','Magnet Thickness')
    field('pole_arc_ed','Pole Arc','deg electrical',maximum=180)
    field('magnet_reduction_mm','Magnet Reduction',inclusive=True)
    field('magnet_width_mm','Magnet Width')
    field('magnet_inset_mm','Magnet Inset',inclusive=True)
    field('magnet_depth_mm','Magnet Depth')
    field('magnet_opening_mm','Magnet Opening',inclusive=True)
    field('rotor_lamination_inset_mm','Rotor Lamination Inset',inclusive=True)
    field('bridge_thickness_mm','Bridge Thickness',structural=True)
    field('web_thickness_mm','Web / Rib Thickness',structural=True)
    field('web_length_mm','Web Length',inclusive=True)
    field('magnet_post_mm','Magnet Post',inclusive=True,structural=True,absent=True)
    field('magnet_clearance_mm','Magnet Clearance',inclusive=True)
    field('magnet_bar_width_mm','Magnet Bar Width')
    field('magnet_separation_mm','Magnet Separation',inclusive=True)
    field('pole_v_angle_md','Pole V Angle','deg mechanical',maximum=180)
    field('mag_gap_inner_mm','Mag Gap Inner',inclusive=True)
    field('mag_gap_outer_mm','Mag Gap Outer',inclusive=True)
    field('magnet_layers','Magnet Layers','count',minimum=1,inclusive=True)
    field('magnet_segments','Magnet Segments','count',minimum=1,inclusive=True)
    # These names have existing checked input usage. This does not mean the
    # independent detailed variable has been connected to the optimizer.
    fields['magnet_thickness_mm'].update(motorcad_variable='Magnet_Thickness',mapping_status='existing_geometry_input')
    fields['pole_arc_ed'].update(motorcad_variable='Magnet_Arc_[ED]',mapping_status='existing_input_readback')
    base=['magnet_thickness_mm','pole_arc_ed','magnet_segments']
    definitions=[
        ('surface_radial','Surface Radial','Surface','Radial',base,False),
        ('surface_parallel','Surface Parallel','Surface','Parallel',base,False),
        ('surface_breadloaf','Surface Breadloaf','Surface','Breadloaf',base+['magnet_reduction_mm'],False),
        ('surface_flat','Surface Flat','Surface',None,base,False),
        ('inset_radial','Inset Radial','Inset',None,base+['magnet_inset_mm'],False),
        ('inset_parallel','Inset Parallel','Inset',None,base+['magnet_inset_mm'],False),
        ('inset_breadloaf','Inset Breadloaf','Inset',None,base+['magnet_inset_mm','magnet_reduction_mm'],False),
        ('embedded_radial','Embedded Radial','Embedded',None,base+['magnet_inset_mm','bridge_thickness_mm'],False),
        ('embedded_parallel','Embedded Parallel','Embedded',None,base+['magnet_inset_mm','bridge_thickness_mm'],False),
        ('embedded_breadloaf','Embedded Breadloaf','Embedded',None,base+['magnet_inset_mm','bridge_thickness_mm','magnet_reduction_mm'],False),
        ('interior_flat_web','Interior Flat (web)','Interior',None,
         base+['bridge_thickness_mm','web_thickness_mm','magnet_post_mm','magnet_clearance_mm','magnet_width_mm'],False),
        ('interior_flat_simple','Interior Flat (simple)','Interior',None,
         ['magnet_thickness_mm','magnet_width_mm','magnet_inset_mm','magnet_segments'],False),
        ('interior_v_web','Interior V (web)','Interior',None,
         ['magnet_layers','magnet_thickness_mm','pole_arc_ed','pole_v_angle_md','magnet_bar_width_mm','magnet_separation_mm',
          'bridge_thickness_mm','web_thickness_mm','web_length_mm','magnet_post_mm','magnet_segments','mag_gap_inner_mm','mag_gap_outer_mm'],True),
        ('interior_v_simple','Interior V (simple)','Interior',None,
         ['magnet_thickness_mm','pole_v_angle_md','magnet_bar_width_mm','magnet_inset_mm','magnet_segments'],False),
        ('interior_u','Interior U-Shape','Interior',None,
         ['magnet_layers','magnet_thickness_mm','pole_arc_ed','magnet_width_mm','bridge_thickness_mm','web_thickness_mm','magnet_segments'],True),
        ('spoke','Spoke','Spoke',None,
         ['magnet_inset_mm','magnet_depth_mm','magnet_opening_mm','magnet_thickness_mm','magnet_segments','rotor_lamination_inset_mm'],False),
    ]
    evidence=json.loads((ROOT/'validation/automation/rotor_enum_evidence.json').read_text(encoding='utf-8'))
    installed=max((v['items'] for v in evidence),key=len)
    assert [r[1] for r in definitions]==installed
    rotors=[]
    for order,(key,label,family,legacy,parameters,layered) in enumerate(definitions):
        verified=order<3
        rotors.append({'id':key,'label':label,'family':family,'input_value':legacy or key,
            'aliases':[label]+([legacy] if legacy else []),'display_order':order,
            'motorcad_rotor_value':order if verified else None,
            'input_mapping_status':'verified' if verified else 'pending',
            'verified_magnetisation':['Radial','Parallel'] if verified else [],
            'direction_policy':'explicit' if verified else 'template_pending',
            'parameters':parameters,'layered':layered,
            'layer_parameters':[p for p in parameters if p!='magnet_layers'] if layered else [],
            'parameter_schema_status':'initial_definition_pending_template_validation',
            'geometry_adapter':'surface_proportional_v1' if order<2 else None,
            'verification_ready_directions':[legacy] if order<2 else [],
            'constraint_ids':['parameter_domain','dimension_grid','geometry_interference','assembly_clearance','material_validity',
                'flux_density','torque_ripple','voltage_current','demagnetization']+
                (['minimum_structural_section'] if family in ('Embedded','Interior','Spoke') else []),
            'design_qualified':False})
    references=[{'id':'radial','rotor_id':'surface_radial','magnetisation':'Radial',
                 'relative_path':'validation/jobs/20261022_132138/calibration.json'},
                {'id':'parallel','rotor_id':'surface_parallel','magnetisation':'Parallel',
                 'relative_path':'validation/calibrations/surface_parallel_20261022/calibration.json'}]
    for r in references:r.update(temperature_C=20,core='POSCO | 50PN470',magnet='JL Mag Rare-Earth | N48UH',poles=4,slots=12,
                                connection='delta',strands=1,paths=1,model='local_surface_proxy_v1')
    data={'schema':'motor-rotor-catalog-v1','version':1,'date':'2026-10-23',
        'scope':'Installed inner-rotor radial-flux BPM standard rotor types; axial/outer/adaptive templates separate',
        'evidence':'validation/automation/rotor_enum_evidence.json','rotors':rotors,'parameter_definitions':fields,
        'reference_models':references,
        'policy':{'dimension_step_mm':.1,'skew_enabled':False,'pole_slot_selection_enabled':True,
            'thermal_analysis_enabled':False,'structural_analysis_enabled':False,'demagnetization_review_enabled':True,
            'minimum_structural_section_mm':.5,'minimum_section_rule':'max(0.5 mm, actual lamination thickness)',
            'manufacturing_rule_source':'User instruction, 2026-10-23; not a mechanical stress qualification',
            'default_pole_slot_pairs':[{'poles':4,'slots':12}]},
        'sources':{'rotor_types':BASE+'rotortype.html','breadloaf':BASE+'surface_breadloaf_magnet_geome.html',
                   'spoke':BASE+'spoke_magnet_geometry.html','ipm_v':BASE+'interior_v_web_magnet_geometry.html',
                   'ipm_flat':BASE+'interior_flat_web_magnet_geome.html'},
        'notes':['Parameter schemas are initial family definitions, not complete SDK mappings.',
                 'Thermal and structural analyses excluded by user. Manufacturing minimum dimensions retained.',
                 'Slot/pole candidates are not proof of a balanced valid winding.']}
    from spm_geometry import STATOR_FIELDS
    data['detailed_spm_geometry']={'registered_rotor_ids':['surface_radial','surface_parallel','surface_breadloaf'],
        'stator_parameters':{key:{'label':label,'native_variable':native,'unit':'mm','step':.1} for key,(label,native) in STATOR_FIELDS.items()},
        'optimizer_connected':False,'breadloaf_native_corner_geometry_verified':False}
    from spm_ripple import SPM_TYPES
    data['spm_ripple_modules']={'scope':list(SPM_TYPES),'module':'validation/spm_ripple.py',
        'status':'experimental_uncalibrated','production_optimizer_connected':False,
        'geometry_input':'native boundary snapshot for each Surface type',
        'acceptance':{'predicted_max_pct':20,'native_max_pct':50,'actual20pct_certification':False}}
    data['spm_ripple_modules']['development_policy']=json.loads(
        (ROOT/'validation/spm_ripple_development_policy.json').read_text(encoding='utf-8'))
    path=ROOT/'interface/rotor-catalog.json'
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Wrote {len(rotors)} rotor definitions, {len(fields)} parameter definitions; no Motor-CAD execution')


if __name__=='__main__':build()
