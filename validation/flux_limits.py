"""Common iron flux-density ceiling for Motor-CAD path maximum outputs (tesla)."""
import math

IRON_FIELDS = (
    'Stator Tooth Flux Density (maximum)',
    'Stator Tooth Tip Flux Density (maximum)',
    'Stator Back Iron Flux Density (maximum)',
    'Rotor Back Iron Flux Density (maximum)',
)


def flux_density_limit(value=None):
    if value is None or value == '':
        return 1.8
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError('Maximum iron flux density must be positive tesla; blank defaults to 1.8 T')
    return float(value)


def flux_density_review(run, value=None):
    limit = flux_density_limit(value)
    regions = {}
    for field in IRON_FIELDS:
        actual = run['values'].get(field)
        usable = isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and actual >= 0
        regions[field] = {'actual_T': actual if usable else None,
                          'passed': actual <= limit if usable else None}
    missing = [k for k, r in regions.items() if r['actual_T'] is None]
    maximum = None if missing else max(r['actual_T'] for r in regions.values())
    passed = False if any(r['passed'] is False for r in regions.values()) else None if missing else True
    return {'limit_T': limit, 'maximum_T': maximum, 'regions': regions,
            'missing_regions': missing, 'passed': passed,
            'status': 'incomplete' if missing else 'pass' if passed else 'exceeded',
            'basis': 'Motor-CAD reported iron path maxima; not a global mesh-element maximum or saturation percentage'}
