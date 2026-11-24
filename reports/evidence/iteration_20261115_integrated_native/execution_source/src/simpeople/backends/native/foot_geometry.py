"""Read-only LBS reconstruction of fixed sole vertices from native joint poses."""
import numpy as np
from pxr import Gf,Usd,UsdGeom,UsdSkel


class FootGeometry:
    def __init__(self,stage,handle,foot_indices):
        if UsdGeom.GetStageUpAxis(stage)!='Z' or abs(UsdGeom.GetStageMetersPerUnit(stage)-1)>1e-12:
            raise ValueError('sole reconstruction currently requires a Z-up metre scene')
        root=stage.GetPrimAtPath(handle);self.skeleton=next(UsdSkel.Skeleton(p) for p in Usd.PrimRange(root) if p.IsA(UsdSkel.Skeleton))
        self.names=list(map(str,self.skeleton.GetJointsAttr().Get()));bind=self.skeleton.GetBindTransformsAttr().Get();self.inverse_bind=np.array([m.GetInverse() for m in bind])
        matrix=UsdGeom.XformCache().GetLocalToWorldTransform(self.skeleton.GetPrim());self.scale=[Gf.Vec3d(*[matrix[r][c] for c in range(3)]).GetLength() for r in range(3)]
        candidates=[]
        for prim in Usd.PrimRange(root):
            if not prim.IsA(UsdGeom.Mesh):continue
            api=UsdSkel.BindingAPI(prim);ip=api.GetJointIndicesPrimvar();wp=api.GetJointWeightsPrimvar()
            if not ip or not wp:continue
            method=api.GetSkinningMethodAttr().Get()
            if method and str(method)!='classicLinear':raise ValueError('sole audit requires classicLinear skinning')
            points=np.array(UsdGeom.Mesh(prim).GetPointsAttr().Get());width=ip.GetElementSize();indices=np.array(ip.ComputeFlattened(),dtype=int).reshape(-1,width);weights=np.array(wp.ComputeFlattened()).reshape(-1,width)
            if len(indices)==1:indices=np.repeat(indices,len(points),axis=0);weights=np.repeat(weights,len(points),axis=0)
            if len(indices)!=len(points):raise ValueError('incomplete sole skin weights')
            mapping=api.GetJointsAttr().Get()
            if mapping:indices=np.array([self.names.index(str(n)) for n in mapping])[indices]
            geom=api.GetGeomBindTransformAttr().Get() or Gf.Matrix4d(1);bound=np.c_[points,np.ones(len(points))]@np.array(geom);bind_world=bound@np.array(matrix)
            for side,foot in foot_indices.items():
                path=self.names[foot];descendants=[i for i,n in enumerate(self.names) if n==path or n.startswith(path+'/')]
                mask=np.sum(weights*np.isin(indices,descendants),axis=1)>.5
                if mask.any():candidates.append({'side':side,'path':str(prim.GetPath()),'ids':np.flatnonzero(mask),'points':bound[mask],'indices':indices[mask],'weights':weights[mask],'bind_z':bind_world[mask,2]})
        self.meshes=[]
        for side in foot_indices:
            group=[m for m in candidates if m['side']==side]
            if not group:raise ValueError('no dominated foot vertices: '+side)
            floor=min(float(m['bind_z'].min()) for m in group)
            for mesh in group:
                mask=mesh['bind_z']<=floor+.008
                if not mask.any():continue
                self.meshes.append({k:(v[mask] if isinstance(v,np.ndarray) else v) for k,v in mesh.items() if k!='bind_z'})
        self.required=sorted({int(i) for m in self.meshes for i in m['indices'].flatten()})

    def describe(self):
        return {'method':'fixed lowest 8mm bind-pose sole band, >50% foot subtree weights, classicLinear reconstruction from actual SDK joint transforms',
            'limitations':'selected deformed vertices; not GPU vertex-buffer readback, exhaustive triangles or contact forces',
            'patches':[{'side':m['side'],'mesh_path':m['path'],'vertex_ids':m['ids'].tolist()} for m in self.meshes]}

    def evaluate(self,world_poses):
        poses=np.array(world_poses,dtype=float)
        if poses.shape!=(len(self.names),7) or not np.isfinite(poses).all():raise ValueError('full finite native pose required for sole reconstruction')
        if np.any(np.abs(np.linalg.norm(poses[:,3:],axis=-1)-1)>.001):raise ValueError('native sole reconstruction requires unit joint rotations')
        skin={}
        for index in self.required:
            p=poses[index];q=p[3:]/np.linalg.norm(p[3:]);matrix=Gf.Matrix4d().SetScale(Gf.Vec3d(*self.scale))*Gf.Matrix4d().SetRotate(Gf.Quatd(float(q[3]),Gf.Vec3d(*map(float,q[:3]))));matrix.SetTranslateOnly(Gf.Vec3d(*map(float,p[:3])));skin[index]=self.inverse_bind[index]@np.array(matrix)
        sides={}
        for mesh in self.meshes:
            result=np.zeros_like(mesh['points'])
            for slot in range(mesh['indices'].shape[1]):
                matrices=np.array([skin[int(i)] for i in mesh['indices'][:,slot]]);result+=np.einsum('ni,nij->nj',mesh['points'],matrices)*mesh['weights'][:,slot,None]
            sides.setdefault(mesh['side'],[]).extend(result[:,:3].tolist())
        return sides
