"""Experimental 1-D radial reluctance/coenergy SPM ripple screening model.

Not an exact subdomain solver. Native magnet boundaries supply actual profiles
for all four Surface types. Slot permeance, iron saturation, tangential flux,
end effects, PWM and Delta circulating current are NOT fully modeled.
No calibration, percent clipping, or forced target satisfaction is performed.
"""
import math
import numpy as np

SPM_TYPES=('surface_radial','surface_parallel','surface_breadloaf','surface_flat')
MU0=4*math.pi*1e-7


def radial_profile(region,angles):
    """Intersect native line/arc boundaries with rays; mm input and output."""
    angles=np.asarray(angles);u=np.column_stack([np.cos(angles),np.sin(angles)])
    hits=[]
    for e in region['entities']:
        a=np.array([e['start']['x'],e['start']['y']]);b=np.array([e['end']['x'],e['end']['y']])
        if e['type']=='line':
            v=b-a;den=u[:,0]*v[1]-u[:,1]*v[0]
            good=np.abs(den)>1e-10
            r=np.divide(a[0]*v[1]-a[1]*v[0],den,out=np.full(len(u),np.nan),where=good)
            t=np.divide(a[0]*u[:,1]-a[1]*u[:,0],den,out=np.full(len(u),np.nan),where=good)
            hits.append(np.where(good&(r>0)&(t>=-1e-8)&(t<=1+1e-8),r,np.nan))
        elif e['type']=='arc':
            center=np.array([e['centre']['x'],e['centre']['y']]);radius=e['radius'];rr=abs(radius)
            dot=u@center;disc=dot*dot-(center@center-rr*rr)
            start=math.atan2(*(a-center)[::-1]);end=math.atan2(*(b-center)[::-1]);sign=1 if radius>0 else -1
            sweep=(sign*(end-start))%(2*math.pi)
            for s in (-1,1):
                r=dot+s*np.sqrt(np.maximum(disc,0));p=r[:,None]*u-center
                angle=np.arctan2(p[:,1],p[:,0]);inside=(sign*(angle-start))%(2*math.pi)<=sweep+1e-8
                hits.append(np.where((disc>=0)&(r>0)&inside,r,np.nan))
        else:raise ValueError('Unsupported native boundary entity')
    if not hits:raise ValueError('Empty magnet boundary')
    h=np.array(hits);valid=np.isfinite(h)
    inner=np.min(np.where(valid,h,np.inf),axis=0);outer=np.max(np.where(valid,h,-np.inf),axis=0)
    count=valid.sum(axis=0);mask=(count>=2)&(outer-inner>1e-7)
    # Shared endpoints can create duplicate hits. More than two distinct radial
    # boundaries mean a radial branch is not a valid representation.
    with np.errstate(invalid='ignore'):
        distinct=np.sum(np.diff(np.sort(np.where(valid,h,np.inf),axis=0),axis=0)>1e-6,axis=0)
    ambiguous=(count>2)&(distinct>2)
    return {'inner_mm':np.where(mask,inner,0),'outer_mm':np.where(mask,outer,0),
        'thickness_mm':np.where(mask,outer-inner,0),'ambiguous_rays':int(ambiguous.sum())}


def derivative(values,bandwidth=48):
    n=len(values);order=np.fft.fftfreq(n,1/n)
    f=np.fft.fft(values,axis=0);shape=(n,)+(1,)*(values.ndim-1)
    # Smooth only unresolved high orders; no change to target or ripple scale.
    if not isinstance(bandwidth,(int,float)) or not 0<bandwidth<n/2:raise ValueError('Fixed bandwidth must be below Nyquist')
    filt=np.exp(-(np.abs(order)/bandwidth)**8)
    return np.fft.ifft(f*(1j*order*filt).reshape(shape),axis=0).real


def ripple(wave):
    mean=float(np.mean(wave));pp=float(np.ptp(wave))
    return {'mean_Nm':mean,'peak_to_peak_Nm':pp,'ripple_pct':100*pp/abs(mean) if abs(mean)>1e-8 else None}


def acceptance(predicted,actual):
    def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
    if not finite(predicted) or predicted>20:return {'state':'not_tested','reason':'No candidate meeting prediction<=20'}
    if not finite(actual):return {'state':'unverified','reason':'Native result unavailable'}
    return {'state':'passed' if actual<=50 else 'failed','predicted_pct':predicted,'actual_pct':actual,
        'actual_20pct_passed':actual<=20,'scope':'Single selected candidate, not family-wide certification'}


def predict(snapshot,spatial_points=1440,rotor_points=240):
    if snapshot['rotor_id'] not in SPM_TYPES:raise ValueError('All four Surface SPM types only')
    p=snapshot['poles'];q=snapshot['slots'];pp=p//2;g=snapshot['geometry_mm']
    if p<2 or p%2 or q<3:raise ValueError('Invalid pole/slot count')
    if spatial_points<360 or rotor_points<120:raise ValueError('Insufficient numerical resolution')
    if snapshot.get('connection')!='delta' or snapshot.get('paths',1)!=1:raise ValueError('Prototype current convention supports Delta, one path only')
    magnet=snapshot['magnet_region'];center=math.atan2(magnet['centroid']['y'],magnet['centroid']['x'])
    period=2*math.pi/p
    local=np.linspace(-period/2,period/2,spatial_points//p+1)
    profile=radial_profile(magnet,local+center)
    if profile['ambiguous_rays']:raise ValueError('Native magnet is not a simple radial-branch profile')
    if not np.any(profile['thickness_mm']>0):raise ValueError('Empty radial magnet profile')
    theta=np.arange(spatial_points)*2*math.pi/spatial_points
    winding=np.zeros((spatial_points,3));turns=snapshot['turns_per_coil']
    for coil in snapshot['coils']:
        start=coil['start']*2*math.pi/q;end=coil['end']*2*math.pi/q
        span=(end-start)%(2*math.pi)
        winding[:,coil['phase']]+=turns*(((theta-start)%(2*math.pi))<span)
    winding-=winding.mean(axis=0)
    bore=g['Stator_Bore']/2000;length=g['Stator_Lam_Length']/1000
    opening=g['Slot_Opening']/1000
    distance=np.abs(((theta+math.pi/q)%(2*math.pi/q))-math.pi/q)*bore
    # Explicit uncalibrated fringing approximation; parameters are NOT fitted to
    # make the validation threshold pass.
    slot_extra=opening/math.pi*np.exp(-2*distance/max(opening,1e-9))
    rotor=np.arange(rotor_points)*2*math.pi/rotor_points
    energy=[];flux=[];inductance=[];tooth_pm=[];tooth_armature=[]
    tooth_index=(np.floor(theta*q/(2*math.pi)+.5).astype(int))%q
    mur=snapshot.get('magnet_mu_r',1.05);br=snapshot['magnet_br_T']
    for alpha in rotor:
        rel=theta-alpha-center;pole=np.floor((rel+period/2)/period).astype(int)
        angle=rel-pole*period
        thickness=np.interp(angle,local,profile['thickness_mm'])/1000
        outer=np.interp(angle,local,profile['outer_mm'])/1000
        active=thickness>1e-9
        iron=(g['Stator_Bore']/2-g['Airgap']-g['Magnet_Thickness'])/1000
        gap=np.where(active,bore-outer,bore-iron)
        if np.any(gap<=0):raise ValueError('Magnet exceeds stator bore')
        direction=np.cos(angle) if snapshot['magnetisation']=='Parallel' else np.ones(len(angle))
        fpm=br*thickness/(MU0*mur)*((-1.)**pole)*direction
        permeance=MU0*length*bore*(2*math.pi/spatial_points)/(gap+slot_extra+thickness/mur)
        total=permeance.sum();pw=permeance@winding;pf=permeance@fpm
        energy.append(.5*(permeance@(fpm*fpm)-pf*pf/total))
        flux.append((permeance*fpm)@winding-pf*pw/total)
        inductance.append(winding.T@(permeance[:,None]*winding)-np.outer(pw,pw)/total)
        tooth_pm.append(np.bincount(tooth_index,weights=permeance*(fpm-pf/total),minlength=q))
        tooth_armature.append(np.column_stack([np.bincount(tooth_index,
            weights=permeance*(winding[:,phase]-pw[phase]/total),minlength=q) for phase in range(3)]))
    energy=np.array(energy);flux=np.array(flux);inductance=np.array(inductance)
    dflux=derivative(flux);dinductance=derivative(inductance);cogging=derivative(energy)
    # Align prescribed fundamental phase currents to the predicted fundamental
    # flux derivative. Never differentiate a changing current as part of torque.
    f=np.fft.fft(dflux,axis=0);fund=np.zeros_like(f);fund[pp]=f[pp];fund[-pp]=f[-pp]
    fundamental=np.fft.ifft(fund,axis=0).real
    amps=np.max(np.abs(fundamental),axis=0)
    if min(amps)<1e-10:raise ValueError('Winding has no PM fundamental coupling')
    phase_peak=snapshot['line_peak_A']/math.sqrt(3)
    current=phase_peak*fundamental/amps
    mutual=np.sum(current*dflux,axis=1)
    reluctance=.5*np.einsum('ni,nij,nj->n',current,dinductance,current)
    torque=cogging+mutual+reluctance;summary=ripple(torque)
    return {'schema':'spm-coenergy-screen-v1','rotor_id':snapshot['rotor_id'],**summary,
        'angle_mechanical_deg':np.degrees(rotor).tolist(),'torque_Nm':torque.tolist(),
        'cogging_Nm':cogging.tolist(),'mutual_Nm':mutual.tolist(),'reluctance_Nm':reluctance.tolist(),
        'spatial_points':spatial_points,'rotor_points':rotor_points,'calibration':'none',
        'qualified':False,'actual_ripple_pct':None,'acceptance':acceptance(summary['ripple_pct'],None),
        'angular_derivative_bandwidth_mechanical_order':48,
        'electromagnetic_state':{'pm_flux_linkage_Wb':flux.tolist(),'phase_inductance_H':inductance.tolist(),
            'reference_phase_current_A':current.tolist(),
            'tooth_pm_flux_Wb':np.asarray(tooth_pm).tolist(),
            'tooth_armature_flux_Wb_per_A':np.asarray(tooth_armature).tolist()},
        'limitations':['Radial reluctance-branch approximation, NOT published exact subdomain equations.',
            'Fixed mechanical-order48 derivative filter; higher-order ripple content is suppressed, not certified absent.',
            'Iron treated as high permeability; saturation and leakage are not solved.',
            'Slot fringing is an uncalibrated approximation; tangential PM magnetization is neglected.',
            'Prescribed sinusoidal currents, no PWM/circulating current or dynamic control.',
            'Delta linepeak to phasepeak conversion; Id=0 approximation only.',
            'Geometry validity, spatial/angular convergence and independent FEA agreement are required.']}
