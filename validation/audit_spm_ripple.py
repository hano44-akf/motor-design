"""Offline, version-specific ripple validation audit. Never starts Motor-CAD."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from spm_ripple import SPM_TYPES, acceptance, ripple
from study_io import write_json


def waveform_summary(wave):
    a = np.asarray(wave, dtype=float)
    if a.ndim != 1 or len(a) < 8 or not np.all(np.isfinite(a)):
        raise ValueError('Finite full-cycle waveform required')
    spectrum = np.fft.rfft(a - a.mean()) / len(a)
    amplitude = 2 * np.abs(spectrum)
    if len(a) % 2 == 0:
        amplitude[-1] /= 2
    orders = sorted(range(1, len(amplitude)), key=lambda k: amplitude[k], reverse=True)[:5]
    return {**ripple(a), 'ac_rms_Nm': float(np.std(a)),
            'dominant_mechanical_orders': [
                {'order': int(k), 'peak_amplitude_Nm': float(amplitude[k])} for k in orders]}


def compare(predicted, actual):
    p = np.asarray(predicted, dtype=float)
    a = np.asarray(actual, dtype=float)
    if p.shape != a.shape:
        raise ValueError('Matching mechanical-cycle grids required')
    ps, ac = waveform_summary(p), waveform_summary(a)
    # Phase search is a diagnostic only: do not replace or refit predictions.
    pc, ca = p - p.mean(), a - a.mean()
    errors = [float(np.mean((np.roll(pc, k) - ca) ** 2)) for k in range(len(p))]
    shift = int(np.argmin(errors))
    return {'prediction': ps, 'native': ac,
            'mean_error_pct': float(100 * (p.mean() - a.mean()) / abs(a.mean())) if abs(a.mean()) > 1e-12 else None,
            'ripple_error_percentage_points': ps['ripple_pct'] - ac['ripple_pct'] if ps['ripple_pct'] is not None and ac['ripple_pct'] is not None else None,
            'peak_to_peak_underprediction_factor': ac['peak_to_peak_Nm'] / ps['peak_to_peak_Nm'] if ps['peak_to_peak_Nm'] > 1e-12 else None,
            'best_circular_shift_mechanical_deg': shift * 360 / len(p),
            'best_shift_ac_rmse_Nm': float(np.sqrt(min(errors))),
            'phase_search_used_for_acceptance': False}


def audit(folder):
    folder = Path(folder).resolve()
    result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
    plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
    calibration = json.loads((folder / 'calibration.json').read_text(encoding='utf-8'))
    rows = []
    for outcome in result['outcomes']:
        if outcome['status'] != 'completed':
            continue
        name = outcome['id']
        proxy_path = folder / (name + '_proxy.json')
        proxy = json.loads(proxy_path.read_text(encoding='utf-8'))
        snapshot = json.loads((folder / (name + '_snapshot.json')).read_text(encoding='utf-8'))
        graph = outcome['graphs']['TorqueMsVw']
        x, y = np.asarray(graph['x']), np.asarray(graph['y'])
        n = len(proxy['torque_Nm'])
        expected_span = 360 * snapshot['poles'] / 2
        if len(x) != n + 1 or len(y) != n + 1 or not np.allclose(np.diff(x), expected_span / n) or not np.isclose(x[-1] - x[0], expected_span):
            raise ValueError('Unrecognized full mechanical-cycle graph: ' + name)
        if not np.allclose(proxy['angle_mechanical_deg'], np.arange(n) * 360 / n):
            raise ValueError('Unrecognized prediction grid: ' + name)
        training = name in calibration['training_ids']
        if training or name in plan['all_prior_native_ids_excluded']:
            raise ValueError('Holdout identity overlaps development data: ' + name)
        raw = np.sum([proxy[k] for k in ('cogging_Nm', 'mutual_Nm', 'reluctance_Nm')], axis=0)
        corrected = compare(proxy['torque_Nm'], y[:-1])
        native_pct = outcome['actual_ripple_pct']
        # CSV is rounded, so permit 0.1 percentage point cross-export difference.
        if not np.isclose(corrected['native']['ripple_pct'], native_pct, atol=.1, rtol=0):
            raise ValueError('Native CSV and waveform ripple disagree: ' + name)
        rows.append({'id': name, 'rotor_id': outcome['rotor_id'],
                     'independent_of_training_ids': True,
                     'calibration_shape_seen': outcome['rotor_id'] in calibration['training_shapes'],
                     'prediction_sha256': hashlib.sha256(proxy_path.read_bytes()).hexdigest(),
                     'raw_comparison': compare(raw, y[:-1]), 'calibrated_comparison': corrected,
                     'native_csv_ripple_pct': native_pct,
                     'acceptance': acceptance(proxy['ripple_pct'], native_pct)})
    families = {}
    for rotor in SPM_TYPES:
        selected = [r for r in rows if r['rotor_id'] == rotor]
        target = [r for r in selected if r['acceptance']['state'] in ('passed', 'failed')]
        families[rotor] = {'independent_cases_this_version': len(selected),
                           'prediction_le20_cases': len(target),
                           'passed_cases': sum(r['acceptance']['state'] == 'passed' for r in target),
                           'failed_cases': sum(r['acceptance']['state'] == 'failed' for r in target),
                           'status': 'failed_observed' if any(r['acceptance']['state'] == 'failed' for r in target) else 'not_demonstrated',
                           'production_optimization_eligible': False}
    report = {'schema': 'spm-ripple-audit-v1', 'source_folder': str(folder),
              'calibration_training_ids': calibration['training_ids'],
              'calibration_training_shapes': calibration['training_shapes'],
              'elapsed_s': result['elapsed_s'], 'cases': rows, 'families': families,
              'production_optimization_eligible': False,
              'scope': 'Frozen predictions, fixed development operating point. No refit, no additional FEA; no family-wide qualification.',
              'next_work': [
                  'Diagnose raw versus corrected harmonic amplitudes before adding FEA.',
                  'Replace cross-family shared correction with geometry/physics-specific treatment; two points do not justify a family fit.',
                  'Audit slot permeance and tangential flux assumptions against saved geometry and waveforms.',
                  'Keep future holdouts separate from development data and freeze model/version before selecting them.',
                  'Require practical predicted<=20/native<=50 evidence before production ripple screening; actual<=20 remains separate.']}
    write_json(folder / 'validation_audit.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.folder)
    print(json.dumps({'cases': len(report['cases']), 'families': report['families']}, indent=2))
