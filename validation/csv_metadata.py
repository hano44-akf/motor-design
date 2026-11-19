"""Explicit known quantity definitions. Unknown units remain unknown."""
NATIVE={
 'D Axis Inductance':('mH','winding_phase; operating_point_d_axis'),
 'Q Axis Inductance':('mH','winding_phase; operating_point_q_axis'),
 'Phase Resistance':('ohm','winding_phase'),
 'Phase Current (rms)':('A','winding_phase_rms'),
 'Phase Current (peak)':('A','winding_phase_peak'),
 'Line Current (peak)':('A','line_peak'),
 'DC Supply Current (mean)':('A','DC_mean; motor_input; inverter_losses_excluded'),
 'Shaft Torque':('N*m','shaft'),
 'Average torque (MsVw)':('N*m','electromagnetic_mean'),
 'System Efficiency':('%','motor_shaft_output_over_motor_input'),
 'Torque Ripple (MsVw) [%]':('%','electromagnetic_torque_peak_to_peak_over_mean'),
 'Line-Line Terminal Voltage (peak)':('V','line_line_peak'),
 'Line-Line Terminal Voltage (rms)':('V','line_line_rms'),
 'Back EMF Line-Line Voltage (peak) (fundamental)':('V','line_line_fundamental_peak'),
 'Back EMF Phase Voltage (peak) (fundamental)':('V','Native_phase_fundamental_peak; connection_dependent'),
 'Shaft Speed':('rpm','mechanical'), 'Fundamental Frequency':('Hz','electrical'),
 'Stator Tooth Flux Density (maximum)':('T','tooth_maximum'),
 'Stator Tooth Tip Flux Density (maximum)':('T','tooth_tip_maximum'),
 'Stator Back Iron Flux Density (maximum)':('T','stator_yoke_maximum'),
 'Rotor Back Iron Flux Density (maximum)':('T','rotor_yoke_maximum')}
FIELDS={
 'estimated_dc_current_A':('A','DC_mean_prediction; ideal_inverter'),
 'dc_current_max_A':('A','DC_mean_maximum'),
 'estimated_current_density_A_mm2':('A/mm^2','winding_phase_rms_over_copper_area'),
 'current_density_max_A_mm2':('A/mm^2','winding_phase_rms_over_copper_area'),
 'phase_peak_A':('A','winding_phase_peak'),'line_peak_A':('A','line_peak'),
 'resistance_ohm':('ohm','winding_phase'),
 'torque_Nm':('N*m','required_shaft'),'estimated_shaft_torque_Nm':('N*m','predicted_shaft'),
 'torque_margin_pct':('%','separate_shaft_capacity_margin'),
 'capacity_torque_Nm':('N*m','required_shaft_capacity; separate_operating_point'),
 'efficiency_pct':('%','predicted_motor_efficiency'),'efficiency_min_pct':('%','motor_efficiency_minimum'),
 'ld_H':('H','winding_phase_d_axis'),'lq_H':('H','winding_phase_q_axis'),
 'Lq_upper_H':('H','winding_phase_q_axis_voltage_budget'),
 'temperature_C':('degC','prescribed_component_temperature'),
 'speed_rpm':('rpm','mechanical'),'voltage_V':('V','DC_bus')}


def metadata(field):
    key=field.rsplit('.',1)[-1]
    if key in NATIVE:return NATIVE[key]
    if key in FIELDS:return FIELDS[key]
    # Declared canonical suffixes, never inferred from ambiguous Native labels.
    if key.endswith('_mm'):return ('mm','design_length')
    if key.endswith('_W'):return ('W','power; see_field_and_source')
    if key.endswith('_s'):return ('s','elapsed_time')
    return ('unknown','unknown')


def evidence_for(field,group,stage):
    if group=='inputs':return 'request'
    if field.startswith('prediction.') or 'control_prediction' in field or field.startswith('operating_control.'):
        return 'formula_prediction'
    if 'formula_review' in field:return 'formula_requirement_assessment'
    if field.startswith('assessment.') or 'requirement_summary' in field:return 'policy_reassessment'
    if group=='motorcad':
        if field.startswith('values.'):return 'saved_FEA'
        if field.startswith(('readback.','geometry_mm.','component_materials.')):return 'saved_solver_readback'
        if field.startswith('design.'):return 'solver_input'
        return 'saved_run_metadata'
    return 'formula_metadata' if stage=='formula' else 'saved_result_or_reassessment'
