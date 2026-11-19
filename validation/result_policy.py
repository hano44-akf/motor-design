"""Solver-independent requirement states; unknown is not a numeric violation."""
import math


def requirement(actual,limit,sense='min'):
    if sense not in ('min','max'):raise ValueError('Unknown requirement direction')
    def usable(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    if limit is None:return {'state':'not_applicable','actual':actual,'limit':None,'shortfall':None}
    if not usable(limit):raise ValueError('Finite requirement limit required')
    if not usable(actual):return {'state':'unverified','actual':None,'limit':limit,'shortfall':None}
    deficit=max(0,limit-actual) if sense=='min' else max(0,actual-limit)
    return {'state':'passed' if deficit==0 else 'violated','actual':actual,'limit':limit,'shortfall':deficit}


def summarize_requirements(items):
    states={key:item['state'] for key,item in items.items()}
    if any(v not in ('passed','violated','unverified','not_applicable') for v in states.values()):raise ValueError('Unknown requirement state')
    missing=[k for k,v in states.items() if v=='unverified'];violated=[k for k,v in states.items() if v=='violated']
    return {'states':states,'unverified':missing,'violated':violated,
        'known_requirements_passed':not violated,'fully_verified':not missing,
        'status':'requirements_violated' if violated else 'verification_incomplete' if missing else 'requirements_passed',
        'passed':not violated and not missing}


def shortfall_summary(shortfalls,references):
    """Known deficits only; caller must use completeness as a separate rank axis."""
    known=0.;missing=[]
    for key,value in shortfalls.items():
        if value is None:missing.append(key);continue
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:raise ValueError('Invalid shortfall')
        known+=value/max(abs(references.get(key) or 1),1e-9)
    return {'known_normalized_shortfall':known,'unverified_requirements':missing,'complete':not missing}


def candidate_rank(assessments,deficits):
    """Independent axes: violations, known deficit, missing evidence.

    Ranking is provisional; absence of a known violation is never certification.
    """
    violations=sum(len(a['requirement_summary']['violated']) for a in assessments)
    missing=sum(len(a['requirement_summary']['unverified']) for a in assessments)
    known=max((d['known_normalized_shortfall'] for d in deficits),default=0.)
    return (violations>0,known,missing)
