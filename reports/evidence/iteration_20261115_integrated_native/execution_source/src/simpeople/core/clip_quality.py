"""Reject malformed native clip samples before any Behavior agent is created."""
import math

LONG_BONES={'L_UpArm','R_UpArm','L_LoArm','R_LoArm','L_LoLeg','R_LoLeg','L_Ankle','R_Ankle'}


def phase_ranges(mode,lo,hi,hold_frames=1,ranges=None):
    if not math.isfinite(lo) or not math.isfinite(hi) or hi<lo:raise ValueError('invalid native clip time range')
    # Behavior does not settle a custom task with a zero-duration loop. The
    # importer authors a duplicate endpoint one sample later for this interval.
    if mode=='transition_then_hold':
        if isinstance(hold_frames,bool) or not isinstance(hold_frames,int) or not 1<=hold_frames<=30:raise ValueError('invalid endpoint hold sample count')
        return {'ActionStart':[lo,hi],'ActionLoop':[hi,hi+hold_frames],'ActionEnd':[hi,hi+hold_frames]}
    if mode=='loop':return {'ActionStart':[lo,lo],'ActionLoop':[lo,hi],'ActionEnd':[lo,lo]}
    if mode=='out_and_back':
        if not isinstance(ranges,dict) or set(ranges)!={'ActionStart','ActionLoop','ActionEnd'}:raise ValueError('explicit native phase ranges required')
        phases={}
        for key in ['ActionStart','ActionLoop','ActionEnd']:
            span=ranges[key]
            if not isinstance(span,list) or len(span)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in span) or not lo<=span[0]<span[1]<=hi:raise ValueError('invalid native phase range')
            phases[key]=list(span)
        if phases['ActionStart'][0]!=lo or phases['ActionEnd'][1]!=hi or phases['ActionStart'][1]>phases['ActionLoop'][0] or phases['ActionLoop'][1]>phases['ActionEnd'][0]:raise ValueError('native phases are not ordered and bounded')
        return phases
    raise ValueError('unsupported native playback mode')


def validate_native_sample(joints,translations,rotations,reference_lengths,max_length_delta=.05):
    if len(joints)!=len(translations) or len(joints)!=len(rotations):
        raise ValueError('native animation joint array size mismatch')
    worst=0.;checked=set()
    for name,p,q in zip(joints,translations,rotations):
        if len(p)!=3 or len(q)!=4 or not all(math.isfinite(float(x)) for x in [*p,*q]):
            raise ValueError('native animation has non-finite transforms')
        if abs(math.sqrt(sum(float(x)**2 for x in q))-1)>.001:
            raise ValueError('native animation has non-unit rotations')
        leaf=str(name).rsplit('/',1)[-1]
        if leaf not in LONG_BONES:continue
        reference=reference_lengths.get(str(name))
        if reference is None or reference<=1e-6:raise ValueError('native target skeleton lacks valid '+leaf)
        delta=abs(math.sqrt(sum(float(x)**2 for x in p))/reference-1)
        if delta>max_length_delta:raise ValueError('native retarget changed bone length: '+leaf)
        worst=max(worst,delta);checked.add(leaf)
    if checked!=LONG_BONES:raise ValueError('native retarget lacks required long bones')
    return worst
