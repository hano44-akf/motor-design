"""Equal-turn, three-phase double-layer winding synthesis; no FEA or skew.

Spatial phasors use positive mechanical angle. Phase axes A/B/C are
0/-120/+120 electrical degrees. This is a candidate winding, not a native
Motor-CAD winding-table readback or proof of manufacturability.
"""
import cmath
import math
from functools import lru_cache


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in [{minimum}, {maximum}]')
    return int(value)


def synthesize(poles, slots, coil_span=None):
    poles = _integer(poles, 'poles', 2, 512)
    slots = _integer(slots, 'slots', 3, 512)
    if poles % 2:
        raise ValueError('Poles must be even')
    if coil_span is not None:
        coil_span = _integer(coil_span, 'coil_span', 1, slots - 1)
    # Cached result is copied: API clients must not mutate subsequent reviews.
    import copy
    return copy.deepcopy(_synthesize(poles, slots, coil_span))


@lru_cache(maxsize=512)
def _synthesize(poles, slots, coil_span):
    step = math.pi * poles / slots
    spans = [coil_span] if coil_span else range(1, min(slots - 1, max(1, math.ceil(slots / poles))) + 1)
    axes = [0, -2 * math.pi / 3, 2 * math.pi / 3]
    candidates = []
    for span in spans:
        vectors = [cmath.exp(1j * step * s) - cmath.exp(1j * step * (s + span)) for s in range(slots)]
        # Midpoint between distinct belt-boundary events avoids arbitrary ties.
        events = sorted({round((cmath.phase(z) - math.pi / 6) % (math.pi / 3), 12) for z in vectors})
        offsets = [(a + (events[(i + 1) % len(events)] + (math.pi / 3 if i == len(events) - 1 else 0))) / 2 for i, a in enumerate(events)]
        for offset in offsets:
            coils = []
            sums = [0j] * 3
            counts = [0] * 3
            for s, z in enumerate(vectors):
                phase, sign = max(((p, sign) for p in range(3) for sign in (1, -1)), key=lambda ps: (z * cmath.exp(-1j * (axes[ps[0]] + offset))).real * ps[1])
                sums[phase] += sign * z
                counts[phase] += 1
                coils.append({'start_slot':s + 1, 'end_slot':(s + span) % slots + 1, 'phase':'ABC'[phase], 'sign':sign})
            kw = [abs(z) / (2 * n) if n else 0 for z, n in zip(sums, counts)]
            angles_ok = all(abs(sums[p] - sums[0] * cmath.exp(1j * axes[p])) < 1e-8 for p in range(3))
            balanced = len(set(counts)) == 1 and min(kw) > 1e-8 and angles_ok
            candidates.append((balanced, min(kw), -span, coils, kw, counts, sums))
    best = max(candidates, key=lambda x:(x[0], round(x[1], 10), x[2]))
    balanced, _, negative_span, coils, kw, counts, sums = best
    harmonics = {}
    for h in (1, 3, 5, 7, 9, 11, 13):
        harmonics[str(h)] = [abs(sum(c['sign'] * (cmath.exp(1j * h * step * (c['start_slot'] - 1)) - cmath.exp(1j * h * step * (c['end_slot'] - 1))) for c in coils if c['phase'] == phase)) / (2 * counts[p]) if counts[p] else 0 for p, phase in enumerate('ABC')]
    return {'poles':poles, 'slots':slots, 'layers':2, 'coil_span_slots':-negative_span,
            'balanced':balanced, 'fundamental_winding_factors':kw, 'coils_per_phase':counts,
            'phase_angles_ed':[math.degrees(cmath.phase(z)) for z in sums],
            'harmonic_winding_factors':harmonics, 'coils':coils,
            'status':'analytical_winding_candidate' if balanced else 'no_balanced_winding_in_supported_family',
            'motorcad_winding_verified':False,
            'scope':'Equal-turn double-layer six-belt family only; harmonics are winding factors, not torque ripple or EMF amplitudes.'}
