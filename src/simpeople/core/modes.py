"""Operational defaults; a mode does not imply a measured people/FPS capacity."""
PROFILES={
 'interactive':{'width':1280,'height':720,'quality_audit':False},
 'generation':{'width':1920,'height':1080,'quality_audit':False},
 'audit':{'width':1920,'height':1080,'quality_audit':True},
 'experimental':{'width':1920,'height':1080,'quality_audit':False}}

def resolve_mode(mode,width=None,height=None,quality_audit=False):
    if mode not in PROFILES:raise ValueError('unsupported runtime mode')
    p=PROFILES[mode];w=p['width'] if width is None else width;h=p['height'] if height is None else height
    if any(isinstance(v,bool) or not isinstance(v,int) or v<64 or v>8192 or v%2 for v in (w,h)):
        raise ValueError('RGB width/height must be even integers between 64 and 8192')
    return {'mode':mode,'width':w,'height':h,'quality_audit':bool(quality_audit or p['quality_audit'])}
