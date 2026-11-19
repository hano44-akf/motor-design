"""Reconstruct the observed standard Breadloaf template, in millimetres.

Derived from saved native line/arc coordinates. Checked against the 16 saved
4p12s templates; not a claim about other Motor-CAD templates or versions.
"""
import math
from magnet_boundary_check import check_region


def boundary(bore_mm, gap_mm, thickness_mm, pole_arc_ed, reduction_mm, poles=4, axis_rad=math.pi/4):
    values=(bore_mm,gap_mm,thickness_mm,pole_arc_ed,reduction_mm,axis_rad)
    if any(not math.isfinite(v) for v in values) or poles<2 or poles%2:
        raise ValueError('Finite dimensions and even positive pole count required')
    if min(bore_mm,gap_mm,thickness_mm)>0 and 0<pole_arc_ed<180 and 0<=reduction_mm<thickness_mm:
        pass
    else:raise ValueError('Invalid Breadloaf dimensions')
    radius=bore_mm/2-gap_mm
    if radius<=thickness_mm:raise ValueError('No rotor iron radius')
    half=math.radians(pole_arc_ed/poles)
    y=radius*math.sin(half);inner=radius-thickness_mm
    outer=radius*math.cos(half)-reduction_mm
    edge=outer-inner
    if edge<=1e-6:raise ValueError('Breadloaf arc crosses backing line: nonpositive edge thickness')
    center=(radius*radius-outer*outer-y*y)/(2*(radius-outer))
    arc_radius=radius-center
    if arc_radius<=0:raise ValueError('Unsupported arc orientation')
    def point(x,y):
        return {'x':x*math.cos(axis_rad)-y*math.sin(axis_rad),
                'y':x*math.sin(axis_rad)+y*math.cos(axis_rad)}
    a,b,c,d=[point(x,z) for x,z in ((inner,-y),(outer,-y),(outer,y),(inner,y))]
    region={'region_type':'Magnet','centroid':point(radius-thickness_mm/2,0),
            'entities':[{'type':'line','start':a,'end':b},
                        {'type':'arc','start':b,'end':c,'centre':point(center,0),'radius':arc_radius},
                        {'type':'line','start':c,'end':d},{'type':'line','start':d,'end':a}]}
    # centroid above supplies the symmetry axis only, not an area centroid.
    if not check_region(region)['passed']:raise ValueError('Constructed boundary intersection')
    return region,{'edge_thickness_along_magnet_axis_mm':edge,
                   'centroid_scope':'Axis marker only, not area centroid',
                   'native_geometry_qualified':False}
