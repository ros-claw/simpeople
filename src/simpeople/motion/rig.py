"""Explicit local/root transforms and full-SOMA/model projection, in metres."""
import hashlib
import json


def rig_digest(rig):
    data={k:rig[k] for k in ['joint_names','parents','reference_local','model_joint_names','model_indices','extra_joint_policy','frame_spec']}
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_rig(rig):
    names=rig['joint_names'];parents=rig['parents'];ref=rig['reference_local'];model=rig['model_joint_names'];indices=rig['model_indices']
    if not names or len(names)!=len(set(names)) or len(parents)!=len(names) or len(ref)!=len(names):raise ValueError('invalid full skeleton')
    if parents[0]!=-1 or any(isinstance(p,bool) or not isinstance(p,int) or not 0<=p<i for i,p in enumerate(parents[1:],1)):raise ValueError('root must be first; parents must precede children')
    if len(model)!=30 or len(indices)!=30 or indices[0]!=0 or names[0]!='Hips':raise ValueError('explicit 30-joint SOMA projection required')
    if any(not 0<=i<len(names) or names[i]!=name for i,name in zip(indices,model)):raise ValueError('model joint mapping mismatch')
    if rig['extra_joint_policy']!='reference':raise ValueError('unsupported extra-joint completion')
    validate_poses([ref],len(names))
    return rig


def validate_poses(poses,joints):
    import numpy as np
    a=np.asarray(poses,dtype=np.float64)
    if a.ndim!=3 or a.shape[1:]!=(joints,7) or a.shape[0]<1 or not np.isfinite(a).all():raise ValueError('expected finite [frames,joints,xyz+xyzw]')
    norms=np.linalg.norm(a[:,:,3:],axis=-1)
    if not np.all(np.abs(norms-1)<=1e-3):raise ValueError('non-unit or zero quaternion')
    return a


def multiply(a,b):
    import numpy as np
    a=np.asarray(a);b=np.asarray(b);v=a[...,:3];u=b[...,:3]
    xyz=a[...,3:]*u+b[...,3:]*v+np.cross(v,u)
    w=a[...,3:]*b[...,3:]-np.sum(v*u,axis=-1,keepdims=True)
    result=np.concatenate([xyz,w],axis=-1)
    return result/np.linalg.norm(result,axis=-1,keepdims=True)


def inverse(q):
    import numpy as np
    q=np.asarray(q).copy();q[...,:3]*=-1;return q


def rotate(q,v):
    import numpy as np
    q=np.asarray(q);q=q/np.linalg.norm(q,axis=-1,keepdims=True);v=np.asarray(v);t=2*np.cross(q[...,:3],v)
    return v+q[...,3:]*t+np.cross(q[...,:3],t)


def forward_kinematics(local,parents):
    import numpy as np
    a=validate_poses(local,len(parents));world=np.empty_like(a)
    for i,parent in enumerate(parents):
        if parent==-1:world[:,i]=a[:,i];continue
        world[:,i,:3]=world[:,parent,:3]+rotate(world[:,parent,3:],a[:,i,:3])
        world[:,i,3:]=multiply(world[:,parent,3:],a[:,i,3:])
    return world


def world_to_local(world,parents):
    import numpy as np
    a=validate_poses(world,len(parents));out=np.empty_like(a)
    for i,parent in enumerate(parents):
        if parent==-1:out[:,i]=a[:,i];continue
        if not 0<=parent<i:raise ValueError('parents must precede children')
        q=inverse(a[:,parent,3:]);out[:,i,:3]=rotate(q,a[:,i,:3]-a[:,parent,:3]);out[:,i,3:]=multiply(q,a[:,i,3:])
    return out


def convert_root(local,rotation):
    import numpy as np
    out=np.asarray(local).copy();out[:,0,:3]=rotate(rotation,out[:,0,:3]);out[:,0,3:]=multiply(rotation,out[:,0,3:])
    return out


def model_parents(rig):
    indices=rig['model_indices'];lookup={v:i for i,v in enumerate(indices)};result=[]
    for i in indices:
        p=rig['parents'][i]
        while p>=0 and p not in lookup:p=rig['parents'][p]
        result.append(lookup.get(p,-1))
    return result


def project_to_model(local,rig):
    import numpy as np
    world=forward_kinematics(local,rig['parents'])[:,rig['model_indices']];out=np.empty_like(world)
    for i,parent in enumerate(model_parents(rig)):
        if parent<0:out[:,i]=world[:,i];continue
        inv=inverse(world[:,parent,3:]);out[:,i,:3]=rotate(inv,world[:,i,:3]-world[:,parent,:3]);out[:,i,3:]=multiply(inv,world[:,i,3:])
    return out


def expand_from_model(model,rig):
    """Position-exact diagnostic expansion, not the official motion decoder.

    A modeled descendant below an unmodeled joint can need a changed local
    translation. Do not use this construction as a bone-length-safe clip.
    """
    import numpy as np
    model_world=forward_kinematics(model,model_parents(rig));lookup={v:i for i,v in enumerate(rig['model_indices'])}
    out=np.repeat(np.asarray(rig['reference_local'])[None,:,:],model_world.shape[0],axis=0);world=np.empty_like(out)
    for i,parent in enumerate(rig['parents']):
        if i in lookup:
            goal=model_world[:,lookup[i]]
            if parent<0:out[:,i]=goal
            else:
                inv=inverse(world[:,parent,3:]);out[:,i,:3]=rotate(inv,goal[:,:3]-world[:,parent,:3]);out[:,i,3:]=multiply(inv,goal[:,3:])
        if parent<0:world[:,i]=out[:,i]
        else:
            world[:,i,:3]=world[:,parent,:3]+rotate(world[:,parent,3:],out[:,i,:3]);world[:,i,3:]=multiply(world[:,parent,3:],out[:,i,3:])
    return out


def decode_reference_pose(model,rig):
    """Mirror the official SOMA decoder's reference lengths/connected rotations.

    Disconnected modeled finger tips are input features but are not decoded.
    Full 77-joint endpoint/context correction is a separate upstream operation.
    """
    import numpy as np
    world=forward_kinematics(model,model_parents(rig));lookup={v:i for i,v in enumerate(rig['model_indices'])}
    out=np.repeat(np.asarray(rig['reference_local'])[None,:,:],len(world),axis=0);connected=set()
    for i,parent in enumerate(rig['parents']):
        if i not in lookup or parent>=0 and parent not in connected:continue
        connected.add(i)
        if parent<0:out[:,i]=world[:,lookup[i]]
        else:out[:,i,3:]=multiply(inverse(world[:,lookup[parent],3:]),world[:,lookup[i],3:])
    return validate_poses(out,len(rig['parents']))
