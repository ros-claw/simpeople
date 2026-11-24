"""CPU reconstruction of selected actual skinned head/neck vertices for audits.

Uses asset geom bind, inverse bind matrices, skin weights and the same native
joint world transforms. Read only, audit mode only. Vertex tests are a lower
bound on mesh penetration (they do not certify every triangle intersection).
"""
import numpy as np
import carb
from pxr import Gf,Usd,UsdGeom,UsdSkel

class HeadNeckGeometry:
    def __init__(self,stage,handle):
        self.meshes=[];self.reason=None
        self.stage_up=UsdGeom.GetStageUpAxis(stage)
        root=stage.GetPrimAtPath(handle)
        skel=next((UsdSkel.Skeleton(p) for p in Usd.PrimRange(root) if p.IsA(UsdSkel.Skeleton)),None)
        if not skel:self.reason='skeleton absent';return
        names=list(skel.GetJointsAttr().Get());bind=skel.GetBindTransformsAttr().Get()
        if not bind or len(bind)!=len(names):self.reason='bind matrices absent';return
        self.names=names
        head={i for i,n in enumerate(names) if n.rsplit('/',1)[-1].rsplit(':',1)[-1].lower()=='head' or n.rsplit('/',1)[-1].rsplit(':',1)[-1].lower().startswith('neck')}
        matrix=UsdGeom.XformCache().GetLocalToWorldTransform(skel.GetPrim())
        self.scale=[Gf.Vec3d(*[matrix[r][c] for c in range(3)]).GetLength() for r in range(3)]
        for prim in Usd.PrimRange(root):
            if not prim.IsA(UsdGeom.Mesh):continue
            api=UsdSkel.BindingAPI(prim);ip=api.GetJointIndicesPrimvar();wp=api.GetJointWeightsPrimvar()
            if not ip or not wp:continue
            method=api.GetSkinningMethodAttr().Get()
            if method and str(method)!='classicLinear':self.reason='unsupported skinning method: '+str(method);continue
            points=np.asarray(UsdGeom.Mesh(prim).GetPointsAttr().Get(),dtype=float);width=ip.GetElementSize()
            indices=np.asarray(ip.ComputeFlattened(),dtype=int).reshape(-1,width)
            weights=np.asarray(wp.ComputeFlattened(),dtype=float).reshape(-1,width)
            if len(indices)==1:indices=np.repeat(indices,len(points),axis=0);weights=np.repeat(weights,len(points),axis=0)
            if len(indices)!=len(points):continue
            mapping=api.GetJointsAttr().Get()
            if mapping:
                lookup={n:i for i,n in enumerate(names)}
                try:indices=np.asarray([lookup[n] for n in mapping],dtype=int)[indices]
                except KeyError:self.reason='joint remapping incomplete';continue
            selected=np.sum(weights*np.isin(indices,list(head)),axis=1)>.25
            if not selected.any():continue
            geom=api.GetGeomBindTransformAttr().Get() or Gf.Matrix4d(1)
            ids=np.flatnonzero(selected);rest=np.concatenate((points[selected],np.ones((len(ids),1))),axis=1)@np.asarray(geom)
            self.meshes.append({'path':str(prim.GetPath()),'ids':ids,'points':rest,'indices':indices[selected],'weights':weights[selected]})
        self.inverse_bind=np.asarray([m.GetInverse() for m in bind])
        self.required=sorted({int(i) for m in self.meshes for i in m['indices'].flatten()})
        self.vertex_count=sum(len(m['ids']) for m in self.meshes)

    def evaluate(self,agent,profile,mpu):
        if not self.meshes:return {'available':False,'reason':self.reason or 'head/neck skin weights absent'}
        # A known tag must map to this exact skeleton order before using indices.
        head=next((i for i,n in enumerate(self.names) if n.rsplit('/',1)[-1].rsplit(':',1)[-1].lower()=='head'),None)
        if head is None or agent.get_joint_index('Head')!=head:return {'available':False,'reason':'native and USD skeleton index order differ'}
        pose={}
        for index in self.required:
            p=carb.Float3(0,0,0);q=carb.Float4(0,0,0,1)
            if not agent.get_joint_world_transform(index,p,q):return {'available':False,'reason':'native joint not ready'}
            matrix=Gf.Matrix4d().SetScale(Gf.Vec3d(*self.scale))*Gf.Matrix4d().SetRotate(Gf.Quatd(q.w,Gf.Vec3d(q.x,q.y,q.z)))
            matrix.SetTranslateOnly(Gf.Vec3d(p.x,p.y,p.z));pose[index]=self.inverse_bind[index]@np.asarray(matrix)
        worst=None;inside=0;front_gap=None
        for mesh in self.meshes:
            output=np.zeros((len(mesh['points']),4))
            for slot in range(mesh['indices'].shape[1]):
                matrices=np.asarray([pose[int(i)] for i in mesh['indices'][:,slot]])
                output+=np.einsum('ni,nij->nj',mesh['points'],matrices)*mesh['weights'][:,slot,None]
            world=output[:,:3]*mpu
            if self.stage_up=='Y':world=world[:,[0,2,1]]*np.asarray([1,-1,1])
            local=world-np.asarray(profile.position_m)
            c=np.cos(profile.yaw_rad);s=np.sin(profile.yaw_rad)
            local=local@np.asarray([[c,-s,0],[s,c,0],[0,0,1]])
            box_local=local-np.asarray(profile.back_center_local_m)
            c=np.cos(profile.back_tilt_rad);s=np.sin(profile.back_tilt_rad)
            y=box_local[:,1].copy();z=box_local[:,2].copy()
            box_local[:,1]=c*y-s*z;box_local[:,2]=s*y+c*z
            q=np.abs(box_local)-np.asarray(profile.back_half_extent_m)
            distances=np.linalg.norm(np.maximum(q,0),axis=1)+np.minimum(q.max(axis=1),0)
            eligible=(np.abs(box_local[:,0])<=profile.back_half_extent_m[0]) & (np.abs(box_local[:,2])<=profile.back_half_extent_m[2])
            if eligible.any():
                gap=float(-profile.back_half_extent_m[1]-box_local[eligible,1].max())
                front_gap=gap if front_gap is None else min(front_gap,gap)
            inside+=int(np.count_nonzero(distances<0));local_id=int(np.argmin(distances));distance=float(distances[local_id])
            if worst is None or distance<worst['clearance_m']:worst={'clearance_m':distance,'mesh_path':mesh['path'],'vertex_index':int(mesh['ids'][local_id]),'world_m':world[local_id].tolist()}
        return {'available':True,'method':'linear skinning of actual asset head/neck vertices, native joint poses',
                'limitation':'vertex penetration only; not exhaustive triangle intersection','tested_vertices':self.vertex_count,'penetrating_vertices':inside,'front_plane_clearance_m':front_gap,'worst':worst}
