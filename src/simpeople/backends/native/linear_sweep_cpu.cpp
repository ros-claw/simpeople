// CPU acceleration of the same vertex-face / edge-edge cubic events as Python.
#include <algorithm>
#include <cmath>
#include <vector>
struct V { double x,y,z; V operator+(V b)const{return{x+b.x,y+b.y,z+b.z};} V operator-(V b)const{return{x-b.x,y-b.y,z-b.z};} V operator*(double s)const{return{x*s,y*s,z*s};} };
double dot(V a,V b){return a.x*b.x+a.y*b.y+a.z*b.z;}
V cross(V a,V b){return{a.y*b.z-a.z*b.y,a.z*b.x-a.x*b.z,a.x*b.y-a.y*b.x};}
double triple(V a,V b,V c){return dot(cross(a,b),c);}
double poly(const double*c,double t){return ((c[0]*t+c[1])*t+c[2])*t+c[3];}
std::vector<double> roots(V* a,V* b,bool&flat){
 V d[4];for(int i=0;i<4;i++)d[i]=b[i]-a[i];V x=a[1]-a[0],y=a[2]-a[0],z=a[3]-a[0],u=d[1]-d[0],v=d[2]-d[0],w=d[3]-d[0];
 double c[4]={triple(u,v,w),triple(u,v,z)+triple(u,y,w)+triple(x,v,w),triple(u,y,z)+triple(x,v,z)+triple(x,y,w),triple(x,y,z)};
 double scale=0;for(double k:c)scale=std::max(scale,std::abs(k));if(scale<1e-13){flat=true;return{};}for(double&k:c)k/=scale;
 std::vector<double> knots{0,1},out;double A=3*c[0],B=2*c[1],C=c[2];
 if(std::abs(A)>1e-11){double D=B*B-4*A*C;if(D>=0){for(double t:{(-B-std::sqrt(D))/(2*A),(-B+std::sqrt(D))/(2*A)})if(t>0&&t<1)knots.push_back(t);}}
 else if(std::abs(B)>1e-11){double t=-C/B;if(t>0&&t<1)knots.push_back(t);}
 std::sort(knots.begin(),knots.end());for(double t:knots)if(std::abs(poly(c,t))<1e-10)out.push_back(t);
 for(unsigned i=1;i<knots.size();i++){double lo=knots[i-1],hi=knots[i],fl=poly(c,lo),fh=poly(c,hi);if(fl*fh>=0)continue;for(int k=0;k<55;k++){double mid=(lo+hi)*.5,fm=poly(c,mid);if(fl*fm<=0){hi=mid;fh=fm;}else{lo=mid;fl=fm;}}out.push_back((lo+hi)*.5);}return out;
}
bool face(V p,V a,V b,V c){V u=b-a,v=c-a,w=p-a;double uu=dot(u,u),uv=dot(u,v),vv=dot(v,v),wu=dot(w,u),wv=dot(w,v),den=uu*vv-uv*uv;if(den<1e-18)return false;double s=(vv*wu-uv*wv)/den,t=(uu*wv-uv*wu)/den;return s>=-1e-7&&t>=-1e-7&&s+t<=1+1e-7;}
bool edge(V a,V b,V c,V d){V u=b-a,v=d-c,w=a-c;double aa=dot(u,u),bb=dot(u,v),cc=dot(v,v),dd=dot(u,w),ee=dot(v,w),den=aa*cc-bb*bb;if(den<1e-18)return false;double s=(bb*ee-cc*dd)/den,t=(aa*ee-bb*dd)/den;V gap=(a+u*s)-(c+v*t);return s>=-1e-7&&s<=1+1e-7&&t>=-1e-7&&t<=1+1e-7&&dot(gap,gap)<1e-12;}
extern "C" void sweep_pairs(const double*A0,const double*A1,const double*B0,const double*B1,int n,double*times,int*unresolved){
 for(int k=0;k<n;k++){V a0[3],a1[3],b0[3],b1[3];for(int j=0;j<3;j++){int i=k*9+j*3;a0[j]={A0[i],A0[i+1],A0[i+2]};a1[j]={A1[i],A1[i+1],A1[i+2]};b0[j]={B0[i],B0[i+1],B0[i+2]};b1[j]={B1[i],B1[i+1],B1[i+2]};}double hit=2;bool flat=false;
 for(int which=0;which<2;which++){V* p0=which?b0:a0,*p1=which?b1:a1,*t0=which?a0:b0,*t1=which?a1:b1;for(int i=0;i<3;i++){V start[4]={t0[0],t0[1],t0[2],p0[i]},end[4]={t1[0],t1[1],t1[2],p1[i]};for(double t:roots(start,end,flat))if(face(p0[i]*(1-t)+p1[i]*t,t0[0]*(1-t)+t1[0]*t,t0[1]*(1-t)+t1[1]*t,t0[2]*(1-t)+t1[2]*t))hit=std::min(hit,t);}}
 for(int i=0;i<3;i++)for(int j=0;j<3;j++){V start[4]={a0[i],a0[(i+1)%3],b0[j],b0[(j+1)%3]},end[4]={a1[i],a1[(i+1)%3],b1[j],b1[(j+1)%3]};for(double t:roots(start,end,flat))if(edge(start[0]*(1-t)+end[0]*t,start[1]*(1-t)+end[1]*t,start[2]*(1-t)+end[2]*t,start[3]*(1-t)+end[3]*t))hit=std::min(hit,t);}
 times[k]=hit<=1?hit:-1;unresolved[k]=flat&&hit>1;
 }
}
