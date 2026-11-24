"""CPU triangle surface intersection for diagnostic pose samples, not dynamics."""
import numpy as np
from scipy.spatial import cKDTree

def triangle_pairs_intersect(a,b,eps=1e-8):
    a=np.asarray(a,float);b=np.asarray(b,float);hit=np.zeros(len(a),bool)
    for source,target in [(a,b),(b,a)]:
        e1=target[:,1]-target[:,0];e2=target[:,2]-target[:,0]
        for i in range(3):
            origin=source[:,i];direction=source[:,(i+1)%3]-origin;p=np.cross(direction,e2);det=np.sum(e1*p,axis=1);valid=np.abs(det)>eps;inverse=np.divide(1.,det,out=np.zeros_like(det),where=valid);v=origin-target[:,0];u=np.sum(v*p,axis=1)*inverse;q=np.cross(v,e1);w=np.sum(direction*q,axis=1)*inverse;t=np.sum(e2*q,axis=1)*inverse;hit|=valid&(u>=-eps)&(w>=-eps)&(u+w<=1+eps)&(t>=-eps)&(t<=1+eps)
    # Coplanar triangles need a 2D separating-axis test; parallel, separated
    # planes are not contacts. Degenerate zero-area triangles are excluded.
    na=np.cross(a[:,1]-a[:,0],a[:,2]-a[:,0]);nb=np.cross(b[:,1]-b[:,0],b[:,2]-b[:,0]);la=np.linalg.norm(na,axis=1);lb=np.linalg.norm(nb,axis=1);normal=np.divide(nb,lb[:,None],out=np.zeros_like(nb),where=lb[:,None]>eps);plane=np.max(np.abs(np.einsum('nij,nj->ni',a-b[:,:1],normal)),axis=1);parallel=np.linalg.norm(np.cross(na,nb),axis=1)<eps*np.maximum(1,la*lb);coplanar=np.flatnonzero(~hit & parallel & (plane<eps)&(la>eps)&(lb>eps))
    for i in coplanar:
        drop=int(np.argmax(np.abs(normal[i])));x=np.delete(a[i],drop,axis=1);y=np.delete(b[i],drop,axis=1);separated=False
        for tri in [x,y]:
            for j in range(3):
                edge=tri[(j+1)%3]-tri[j];axis=np.array([-edge[1],edge[0]]);px=x@axis;py=y@axis
                if px.max()<py.min()-eps or py.max()<px.min()-eps:separated=True;break
            if separated:break
        hit[i]=not separated
    return hit

def surface_intersections(a,b):
    a=np.asarray(a);b=np.asarray(b);ca=a.mean(axis=1);cb=b.mean(axis=1);ra=np.linalg.norm(a-ca[:,None],axis=2).max(axis=1);rb=np.linalg.norm(b-cb[:,None],axis=2).max(axis=1);tree=cKDTree(cb);candidates=tree.query_ball_point(ca,ra+float(rb.max())+1e-8);ia=[];ib=[];blo=b.min(axis=1);bhi=b.max(axis=1)
    for i,js in enumerate(candidates):
        if not js:continue
        js=np.array(js,dtype=int);mask=np.all(a[i].max(axis=0)>=blo[js]-1e-8,axis=1)&np.all(a[i].min(axis=0)<=bhi[js]+1e-8,axis=1);js=js[mask];ia.extend([i]*len(js));ib.extend(js.tolist())
    if not ia:return {'candidate_pairs':0,'intersecting_pairs':0}
    mask=triangle_pairs_intersect(a[np.array(ia)],b[np.array(ib)]);return {'candidate_pairs':len(ia),'intersecting_pairs':int(mask.sum())}
