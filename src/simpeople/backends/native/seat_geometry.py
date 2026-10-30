"""Fingerprint authored chair surface/back/effector geometry, excluding placement."""
import hashlib
import json

def seat_geometry_hash(stage,seat):
    root=seat['prim_path'];back=stage.GetPrimAtPath(seat.get('back_prim_path',root+'/Back'))
    surface=stage.GetPrimAtPath(seat.get('surface_prim_path',root+'/Seat'))
    if not surface:surface=stage.GetPrimAtPath(root+'/Cushion')
    hips=stage.GetPrimAtPath(seat['hips_prim_path'])
    if not all((back,surface,hips)):return None
    record={}
    for role,prim in [('back',back),('surface',surface),('hips',hips)]:
        record[role]={str(a.GetName()):str(a.Get()) for a in prim.GetAttributes()
                      if str(a.GetName()).startswith('xformOp') or str(a.GetName()) in {'points','faceVertexCounts','faceVertexIndices'}}
    return hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()
