"""Numerical contract for an explicit, offline sequence of SDK retarget stages."""
import numpy as np


def retarget_chain(local, stages):
    """Each (name, output joint count, callback) maps one local pose at a time.

    Keep raw stage output as evidence. Normalize only bounded SDK quaternion
    roundoff, before the next stage consumes it. This writes no actor pose.
    """
    values=np.asarray(local,dtype=float)
    if values.ndim!=3 or values.shape[-1]!=7 or not len(values) or not np.isfinite(values).all():
        raise ValueError('finite nonempty local pose sequence required')
    records={};errors={}
    for name,count,apply in stages:
        if not isinstance(name,str) or not name or name in records or type(count) is not int or count<1:
            raise ValueError('unique retarget stage and positive joint count required')
        raw=np.asarray([apply(pose.copy()) for pose in values],dtype=float)
        if raw.shape!=(len(values),count,7) or not np.isfinite(raw).all():
            raise ValueError('SDK stage returned invalid pose shape or values: '+name)
        norms=np.linalg.norm(raw[:,:,3:],axis=-1);error=float(abs(norms-1).max())
        if error>.01:
            raise ValueError('SDK stage quaternion error exceeds normalization bound: '+name)
        records[name]=raw.copy();errors[name]=error
        values=raw.copy();values[:,:,3:]/=norms[:,:,None]
    if not records:
        raise ValueError('at least one explicit retarget stage required')
    return values,records,errors
