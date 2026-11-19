"""Exact line/arc self-intersection screen in native mm coordinates.

Necessary boundary checks only; not a mesh or manufacturing certification.
"""
import math
import numpy as np

TOL=1e-6


def point(p):return np.array([p['x'],p['y']],dtype=float)
def cross(a,b):return float(a[0]*b[1]-a[1]*b[0])


def on_arc(p,e):
    c=point(e['centre']);r=e['radius'];a=point(e['start'])-c;b=point(e['end'])-c;v=p-c
    sign=1 if r>0 else -1
    start=math.atan2(a[1],a[0]);end=math.atan2(b[1],b[0]);angle=math.atan2(v[1],v[0])
    return (sign*(angle-start))%(2*math.pi)<=(sign*(end-start))%(2*math.pi)+1e-8


def intersections(a,b):
    if a['type']=='arc' and b['type']=='line':return intersections(b,a)
    p=point(a['start']);q=point(a['end'])
    if a['type']=='line' and b['type']=='line':
        r=point(b['start']);s=point(b['end']);u=q-p;v=s-r;den=cross(u,v)
        if abs(den)<1e-12:
            if abs(cross(r-p,u))>TOL:return []
            uu=float(u@u)
            if uu<TOL*TOL:return [p]
            lo,hi=sorted((float((r-p)@u/uu),float((s-p)@u/uu)))
            low=max(0,lo);high=min(1,hi)
            if high<low-1e-9:return []
            return [p+u*low] if high-low<1e-8 else [p+u*low,p+u*high,p+u*((low+high)/2)]
        t=cross(r-p,v)/den;z=cross(r-p,u)/den
        return [p+t*u] if -1e-9<=t<=1+1e-9 and -1e-9<=z<=1+1e-9 else []
    if a['type']=='line' and b['type']=='arc':
        c=point(b['centre']);r=abs(b['radius']);u=q-p;d=p-c
        aa=float(u@u);bb=2*float(d@u);cc=float(d@d)-r*r
        disc=bb*bb-4*aa*cc
        if aa<1e-15 or disc<-1e-9:return []
        out=[]
        for t in ((-bb-math.sqrt(max(0,disc)))/(2*aa),(-bb+math.sqrt(max(0,disc)))/(2*aa)):
            x=p+t*u
            if -1e-9<=t<=1+1e-9 and on_arc(x,b) and not any(np.linalg.norm(x-y)<TOL for y in out):out.append(x)
        return out
    c=point(a['centre']);d=point(b['centre']);r=abs(a['radius']);s=abs(b['radius']);v=d-c;distance=float(np.linalg.norm(v))
    if distance<TOL:
        if abs(r-s)>TOL:return []
        # Coincident arcs: overlap anywhere other than their shared endpoints
        # is not a simple boundary.
        sign=1 if a['radius']>0 else -1
        start=math.atan2(*(p-c)[::-1]);end=math.atan2(*(q-c)[::-1]);sweep=sign*(end-start)%(2*math.pi)
        pts=[p,q,c+r*np.array([math.cos(start+sign*sweep/2),math.sin(start+sign*sweep/2)])]
        pts.extend([point(b['start']),point(b['end'])])
        return [x for x in pts if on_arc(x,a) and on_arc(x,b)]
    if distance>r+s+TOL or distance<abs(r-s)-TOL:return []
    along=(r*r-s*s+distance*distance)/(2*distance);height=math.sqrt(max(0,r*r-along*along));unit=v/distance
    mid=c+along*unit;normal=np.array([-unit[1],unit[0]])
    return [x for x in (mid+height*normal,mid-height*normal) if on_arc(x,a) and on_arc(x,b)]


def check_region(region):
    edges=region.get('entities',[]);issues=[]
    if len(edges)<3:return {'passed':False,'issues':[{'reason':'too_few_edges'}]}
    for i,e in enumerate(edges):
        if e['type'] not in ('line','arc'):return {'passed':False,'issues':[{'reason':'unsupported_entity'}]}
        points=[point(e['start']),point(e['end'])]+([point(e['centre'])] if e['type']=='arc' else [])
        if any(not np.all(np.isfinite(p)) for p in points):return {'passed':False,'issues':[{'reason':'nonfinite_boundary'}]}
        if e['type']=='arc' and (not math.isfinite(e['radius']) or abs(e['radius'])<TOL):return {'passed':False,'issues':[{'reason':'invalid_arc_radius'}]}
        if np.linalg.norm(point(e['end'])-point(edges[(i+1)%len(edges)]['start']))>TOL:issues.append({'reason':'open_boundary','edge':i})
        if np.linalg.norm(point(e['end'])-point(e['start']))<TOL:issues.append({'reason':'zero_length_edge','edge':i})
    for i,a in enumerate(edges):
        for j in range(i+1,len(edges)):
            b=edges[j];shared=[point(a[k]) for k in ('start','end') for l in ('start','end') if np.linalg.norm(point(a[k])-point(b[l]))<TOL]
            for x in intersections(a,b):
                if (j==i+1 or (i==0 and j==len(edges)-1)) and any(np.linalg.norm(x-s)<TOL for s in shared):continue
                issues.append({'reason':'self_intersection','edges':[i,j],'point_mm':x.tolist()})
    return {'passed':not issues,'issues':issues,'scope':'Boundary closure and self-intersection only; no mesh or manufacturing qualification'}
