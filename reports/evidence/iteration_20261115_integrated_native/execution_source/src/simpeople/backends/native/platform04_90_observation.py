"""Actual UsdSkel/mesh readback and actor-specific, rendered visibility.

The unobstructed denominator is an opaque CPU triangle silhouette of the actual
deformed USD meshes, at the production camera and resolution. Hair alpha and
translucent materials are not reproduced; that uncertainty remains explicit.
"""
import ctypes,json,subprocess
from pathlib import Path
import numpy as np
from pxr import Usd,UsdGeom


def triangulate(mesh):
    result=[];cursor=0;indices=list(mesh.GetFaceVertexIndicesAttr().Get())
    for count in mesh.GetFaceVertexCountsAttr().Get():
        for j in range(1,count-1):result.append([indices[cursor],indices[cursor+j],indices[cursor+j+1]])
        cursor+=count
    return np.array(result,dtype=int)


class PerformanceReadback:
    JOINTS={'nose':'Head','chin':'Head','l_ear':'Head','r_ear':'Head',
            'chest':'Spine02','l_shoulder':'L_Upperarm','r_shoulder':'R_Upperarm',
            'l_elbow':'L_Forearm','r_elbow':'R_Forearm','l_wrist':'L_Hand','r_wrist':'R_Hand',
            'l_knee':'L_Calf','r_knee':'R_Calf','l_ankle':'L_Foot','r_ankle':'R_Foot',
            'l_toe':'L_ToeBase','r_toe':'R_ToeBase'}
    def __init__(self,root,out,actors,resolution=(1920,1080)):
        self.root=Path(root);self.out=Path(out);self.actors=actors;self.w,self.h=resolution;self.topology={};self.anchors={};self.heights={}
        source=self.root/'.runtime/platform04_90/kit/motion/raster.c';lib=self.out/'single_actor_silhouette.so';subprocess.run(['gcc','-shared','-fPIC','-O3',str(source),'-o',str(lib),'-lm'],check=True);self.lib=ctypes.CDLL(str(lib));ptr=ctypes.c_void_p;self.lib.frame.argtypes=[ptr,ptr,ctypes.c_int,ctypes.c_int,ptr,ptr,ptr,ctypes.c_int,ptr,ctypes.c_float];self.lib.frame.restype=None;self.picture=np.empty((self.h,self.w,3),np.uint8);self.depth=np.empty((self.h,self.w),np.float32)
        for aid,actor in actors.items():
            for m in actor.meshes:self.topology[str(m['prim'].GetPath())]=triangulate(UsdGeom.Mesh(m['prim']))
            # Standing height is independently calibrated before crouch/action.
            actor.safe_update(actor.cache.pose(0,'idle'),[0,0,0]);pts=actor.skin_points();cloud=np.concatenate([pts[str(m['prim'].GetPath())] for m in actor.meshes if str(UsdGeom.Imageable(m['prim']).ComputeVisibility())!='invisible']);self.heights[aid]=float(np.ptp(cloud[:,2]))
        (self.out/'visibility_method.json').write_text(json.dumps({'instance_pixels':'actual current-camera leaf instance ID render','denominator':'CPU opaque triangle silhouette from actual deformed USD skin + prop meshes, same camera and 1920x1080 resolution','markers':'fixed actual skinned vertex IDs per camera shot, selected near named actual FK joints on the camera-facing surface; marker visibility checked against actor instance ID and its isolated-silhouette depth','limits':['hair alpha/cutout and translucent shading not modeled in CPU denominator','glass may hide instance IDs despite visible transmitted RGB; glass diagnostic conditions are explicitly labeled','insufficient visible markers/short intervals remain unjudged','this is not a naturalness or fear classifier']},indent=2))
    def read_actor(self,aid,with_skin=True):
        actor=self.actors[aid];stage=actor.stage;xf=UsdGeom.XformCache();root_matrix=xf.GetLocalToWorldTransform(stage.GetPrimAtPath(actor.path));matrix=np.asarray(root_matrix);query=actor.skin
        # Invalidate cached UsdSkel queries after authoring animation attributes.
        query.Clear();query.Populate(actor.skin_root,Usd.PrimDefaultPredicate);q=query.GetSkelQuery(actor.skeleton);joint_sk=q.ComputeJointSkelTransforms(Usd.TimeCode.Default());sk_world=xf.GetLocalToWorldTransform(actor.skeleton.GetPrim());joints=np.array([(m*sk_world).ExtractTranslation() for m in joint_sk]);parts=[];triangles=[];part_paths=[]
        if with_skin:
            skin=actor.skin_points()
            for mesh in actor.meshes:
                path=str(mesh['prim'].GetPath())
                if str(UsdGeom.Imageable(mesh['prim']).ComputeVisibility())=='invisible':continue
                p=skin[path]@matrix[:3,:3]+matrix[3,:3];parts.append(p);triangles.append(p[self.topology[path]]);part_paths.append(path)
            # Include the actor's separately attached bags/straps, rather than
            # counting them in the numerator but omitting their silhouette.
            known=set(self.topology)
            for prim in Usd.PrimRange(stage.GetPrimAtPath(actor.path)):
                path=str(prim.GetPath())
                if not prim.IsA(UsdGeom.Mesh) or path in known or str(UsdGeom.Imageable(prim).ComputeVisibility())=='invisible':continue
                mesh=UsdGeom.Mesh(prim);m=np.asarray(xf.GetLocalToWorldTransform(prim));p=np.asarray(mesh.GetPointsAttr().Get())@m[:3,:3]+m[3,:3];parts.append(p);triangles.append(p[triangulate(mesh)]);part_paths.append(path)
        return {'root_matrix':matrix,'joints_world_m':joints,'cloud':np.concatenate(parts) if parts else None,'parts':parts,'part_paths':part_paths,'triangles':np.concatenate(triangles) if triangles else None}
    def visibility(self,aid,actual,ids,labels,camera_matrix,focal_mm,shot,frame,state):
        prefix=self.actors[aid].path+'/';numbers=[int(k) for k,v in labels.items() if str(v).startswith(prefix)];mask=np.isin(ids,numbers) if numbers else np.zeros((self.h,self.w),bool);mask_px=int(mask.sum());root=actual['root_matrix'];yaw=np.arctan2(root[0,1],root[0,0]);result={'shot':shot,'f':int(frame),'id':aid,'root_m':root[3,:3].tolist(),'yaw_deg':float(np.degrees(yaw)),'height_m':self.heights[aid],'box_px':0.,'mask_px':mask_px,'visible_fraction':0.,'visible_joints':[],'pose_local_m':{},'mode':state['behavior'],'silhouette_px':0,'visibility_scope':'current rendered leaf IDs / same-camera actual-mesh opaque CPU isolated silhouette'}
        if not mask_px:return result
        cam=np.asarray(camera_matrix);camera=np.ascontiguousarray(np.r_[cam[3,:3],cam[0,:3],cam[1,:3],-cam[2,:3]],np.float32);tri=np.ascontiguousarray(actual['triangles'],np.float32);colors=np.full((len(tri),3),200,np.uint8);kind=np.full(len(tri),2,np.uint8);focal=self.w*focal_mm/36;self.lib.frame(self.picture.ctypes.data,self.depth.ctypes.data,self.w,self.h,tri.ctypes.data,colors.ctypes.data,kind.ctypes.data,len(tri),camera.ctypes.data,float(focal));single=self.depth<1e9;den=int(single.sum());result['silhouette_px']=den;result['visible_fraction']=min(1.,mask_px/max(1,den))
        cloud=actual['cloud'];local=(cloud-cam[3,:3])@cam[:3,:3].T;valid=local[:,2]<-.095;ys=self.h/2-focal*local[valid,1]/(-local[valid,2]);result['box_px']=float(np.ptp(ys)) if len(ys) else 0
        key=(shot,aid)
        if key not in self.anchors:
            from PIL import Image
            overlay=np.zeros((self.h,self.w,3),np.uint8);overlay[single&mask]=[60,200,120];overlay[single&~mask]=[70,150,230];overlay[mask&~single]=[230,70,160];Image.fromarray(overlay).save(self.out/f'mask_compare_{shot.rsplit(":",1)[-1]}_{aid}.png')
            anchors={}
            for marker,bone in self.JOINTS.items():
                j=actual['joints_world_m'][self.actors[aid].cache.index(bone)].copy()
                if marker in ['nose','chin','l_ear','r_ear']:
                    offset={'nose':[.085,0,.035],'chin':[.055,0,-.035],'l_ear':[0,.075,.035],'r_ear':[0,-.075,.035]}[marker];j+=np.array(offset)@root[:3,:3]
                distance=np.linalg.norm(cloud-j,axis=1);candidate=np.flatnonzero(distance<(.20 if marker=='chest' else .12))
                if not len(candidate):candidate=np.argsort(distance)[:12]
                to_camera=cam[3,:3]-j;to_camera/=np.linalg.norm(to_camera);score=(cloud[candidate]-j)@to_camera-.25*distance[candidate];anchors[marker]=int(candidate[score.argmax()])
            self.anchors[key]=anchors
        for marker,i in self.anchors[key].items():
            point=cloud[i];p=(point-cam[3,:3])@cam[:3,:3].T;z=-p[2]
            if z<=.095:continue
            x=int(round(self.w/2+focal*p[0]/z));y=int(round(self.h/2-focal*p[1]/z))
            if not 2<=x<self.w-2 or not 2<=y<self.h-2:continue
            own=bool(mask[y-2:y+3,x-2:x+3].any());front=float(self.depth[y-2:y+3,x-2:x+3].min())
            if own and abs(z-front)<.045:result['visible_joints'].append(marker)
            result['pose_local_m'][marker]=((point-root[3,:3])@root[:3,:3].T).tolist()
        return result
