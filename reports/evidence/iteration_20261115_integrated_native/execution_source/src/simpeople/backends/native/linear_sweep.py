"""Triangle CCD for a piecewise-linear vertex-motion approximation.

This does not assert that an articulated animation is linear between samples.
Persistently coplanar event polynomials are reported as unresolved, never passed.
"""
import numpy as np
import ctypes,hashlib,subprocess,tempfile
from pathlib import Path
from scipy.spatial import cKDTree
from .mesh_intersections import triangle_pairs_intersect


def coplanarity_roots(points0, points1):
    a=np.asarray(points0,float);b=np.asarray(points1,float)-a
    x,y,z=a[1:]-a[0];u,v,w=b[1:]-b[0]
    triple=lambda a,b,c:float(np.dot(np.cross(a,b),c))
    coefficients=np.array([triple(u,v,w),triple(u,v,z)+triple(u,y,w)+triple(x,v,w),
        triple(u,y,z)+triple(x,v,z)+triple(x,y,w),triple(x,y,z)])
    scale=float(np.max(np.abs(coefficients)))
    if scale<1e-13:return [],True
    first=next(i for i,c in enumerate(coefficients) if abs(c)>scale*1e-11)
    roots=np.roots(coefficients[first:]) if first<3 else []
    return sorted(float(np.clip(x.real,0,1)) for x in roots
        if abs(x.imag)<1e-7 and -1e-8<=x.real<=1+1e-8),False


def in_face(p, triangle):
    a,b,c=triangle;u=b-a;v=c-a;w=p-a
    uu=float(u@u);uv=float(u@v);vv=float(v@v);wu=float(w@u);wv=float(w@v)
    determinant=uu*vv-uv*uv
    if determinant<1e-18:return False
    s=(vv*wu-uv*wv)/determinant;t=(uu*wv-uv*wu)/determinant
    return s>=-1e-7 and t>=-1e-7 and s+t<=1+1e-7


def edges_touch(a,b,c,d):
    u=b-a;v=d-c;w=a-c;aa=float(u@u);bb=float(u@v);cc=float(v@v);dd=float(u@w);ee=float(v@w);den=aa*cc-bb*bb
    if den<1e-18:return False
    s=(bb*ee-cc*dd)/den;t=(aa*ee-bb*dd)/den
    return -1e-7<=s<=1+1e-7 and -1e-7<=t<=1+1e-7 and np.linalg.norm((a+s*u)-(c+t*v))<1e-6


def triangle_sweep(a0,a1,b0,b1):
    a0,a1,b0,b1=map(lambda x:np.asarray(x,float),(a0,a1,b0,b1))
    if triangle_pairs_intersect(a0[None],b0[None])[0]:return 0.,False
    if triangle_pairs_intersect(a1[None],b1[None])[0]:return 1.,False
    unresolved=False;hit=None
    for p0,p1,t0,t1 in [(a0,a1,b0,b1),(b0,b1,a0,a1)]:
        for i in range(3):
            roots,flat=coplanarity_roots(np.vstack([t0,p0[i]]),np.vstack([t1,p1[i]]));unresolved|=flat
            for time in roots:
                if in_face(p0[i]*(1-time)+p1[i]*time,t0*(1-time)+t1*time):
                    hit=time if hit is None else min(hit,time)
    for i in range(3):
        for j in range(3):
            ids=[i,(i+1)%3];js=[j,(j+1)%3];start=np.vstack([a0[ids],b0[js]]);end=np.vstack([a1[ids],b1[js]]);roots,flat=coplanarity_roots(start,end);unresolved|=flat
            for time in roots:
                p=start*(1-time)+end*time
                if edges_touch(*p):hit=time if hit is None else min(hit,time)
    return hit,unresolved


def swept_surface_intersections(a0,a1,b0,b1):
    a0,a1,b0,b1=map(np.asarray,(a0,a1,b0,b1));a=np.concatenate([a0,a1],axis=1);b=np.concatenate([b0,b1],axis=1);ca=a.mean(1);cb=b.mean(1);ra=np.linalg.norm(a-ca[:,None],axis=2).max(1);rb=np.linalg.norm(b-cb[:,None],axis=2).max(1);neighbors=cKDTree(cb).query_ball_point(ca,ra+float(rb.max())+1e-8);low=b.min(1);high=b.max(1);hits=[];unresolved=0;candidate_count=0
    pairs=[]
    for i,js in enumerate(neighbors):
        if not js:continue
        js=np.array(js,dtype=int);keep=np.all(a[i].max(0)>=low[js]-1e-8,axis=1)&np.all(a[i].min(0)<=high[js]+1e-8,axis=1)
        pairs.extend((i,int(j)) for j in js[keep])
    candidate_count=len(pairs)
    if pairs:
        ia,ib=np.array(pairs).T;aa0,aa1,bb0,bb1=[np.ascontiguousarray(v,dtype=np.float64) for v in [a0[ia],a1[ia],b0[ib],b1[ib]]]
        times,flat=native_pair_events(aa0,aa1,bb0,bb1)
        for k,time in enumerate(times):
            if time>=0:hits.append({'triangle_a':int(ia[k]),'triangle_b':int(ib[k]),'fraction':float(time)})
        unresolved=int(flat.sum())
    return {'candidate_pairs':candidate_count,'contact_pairs':len(hits),'contacts':hits[:8],
            'unresolved_coplanar_pairs':unresolved,'scope':'linear vertex sweep between samples; unresolved coplanar cases are not certified clear'}


_library=None
def native_pair_events(a0,a1,b0,b1):
    """Same event equations, batched in CPU C++; endpoint tests stay vectorized."""
    global _library
    if _library is None:
        source=Path(__file__).with_name('linear_sweep_cpu.cpp');digest=hashlib.sha256(source.read_bytes()).hexdigest()[:20];target=Path(tempfile.gettempdir())/f'simpeople_sweep_{digest}.so'
        if not target.exists():
            temporary=target.with_suffix('.tmp.so');subprocess.run(['g++','-O3','-std=c++17','-shared','-fPIC',str(source),'-o',str(temporary)],check=True);temporary.replace(target)
        _library=ctypes.CDLL(str(target));pointer=ctypes.POINTER(ctypes.c_double);_library.sweep_pairs.argtypes=[pointer]*4+[ctypes.c_int,pointer,ctypes.POINTER(ctypes.c_int)]
    times=np.full(len(a0),-1.,dtype=np.float64);flat=np.zeros(len(a0),dtype=np.int32);start=triangle_pairs_intersect(a0,b0);end=triangle_pairs_intersect(a1,b1);times[end]=1.;times[start]=0.;selected=np.flatnonzero(~(start|end))
    if len(selected):
        arrays=[np.ascontiguousarray(a[selected],dtype=np.float64) for a in [a0,a1,b0,b1]];tt=np.empty(len(selected),dtype=np.float64);ff=np.empty(len(selected),dtype=np.int32);pointer=ctypes.POINTER(ctypes.c_double);_library.sweep_pairs(*[a.ctypes.data_as(pointer) for a in arrays],len(selected),tt.ctypes.data_as(pointer),ff.ctypes.data_as(ctypes.POINTER(ctypes.c_int)));times[selected]=tt;flat[selected]=ff
    return times,flat
