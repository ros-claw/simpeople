"""Frame-driven film blocking and measured cinematic boarding interlocks.

This is a movie controller. All actors use full-pose caches with a single
transform owner; neither the crowd nor the railway is claimed to be PhysX.
"""
import json,math
from pathlib import Path
import numpy as np
from pxr import Gf,UsdGeom,UsdShade,Sdf,Vt
from simpeople.core.deadweight import DeadweightDispatch
from .deadweight_cinema import FilmActor,raised_wings,torso_sway,infected_wait
from .deadweight_set import RUN,FLOOR,WIDTH,box,label


def smooth(v):
    v=np.clip(v,0,1);return float(v*v*(3-2*v))


class Route:
    def __init__(self,points):
        self.points=np.asarray(points,dtype=float)
        self.lengths=np.linalg.norm(np.diff(self.points,axis=0),axis=1)
        self.cumulative=np.r_[0,np.cumsum(self.lengths)]
        self.length=float(self.cumulative[-1])

    def at(self,distance):
        distance=float(np.clip(distance,0,self.length));j=min(len(self.lengths)-1,int(np.searchsorted(self.cumulative,distance,side='right')-1))
        vector=self.points[j+1]-self.points[j];u=(distance-self.cumulative[j])/max(self.lengths[j],1e-9)
        return self.points[j]+vector*u,float(math.atan2(vector[1],vector[0]))


class DeadweightDirector:
    def __init__(self,stage,cars,cache,root,mode='full'):
        self.stage=stage;self.cars=cars;self.cache=cache;self.root=root;self.mode=mode
        self.count=23 if mode=='full' else 6
        self.dispatch=DeadweightDispatch(threshold_kg=1745.94 if mode=='full' else 6*74+76)
        self.actors={};self.records=[];self.stable={};self.arrivals={};self.boarded=[];self.events=[]
        assets=json.loads((root/'configs/assets.json').read_text())['assets'][:11]
        self.palette=[(.18,.39,.41),(.61,.25,.10),(.25,.33,.16),(.16,.24,.42),(.49,.16,.19),(.45,.38,.16)]
        def source(k):
            asset=assets[k%len(assets)];return str(root/'assets/characters'/asset['source_uri'].removeprefix('characters://'))
        portal_counts={1:0,2:0}
        for i in range(self.count):
            aid=f'infected_{i+1:02d}';actor=FilmActor(stage,cars['A']['root']+'/Passengers/'+aid,cache,self.palette[i%6],source(i))
            actor.rainwear(self.palette[i%6]);self.actors[aid]=actor
            # Wide 1.1m slots, far side filled first. Two independent portals.
            row=i%8;col=i//8;slot=np.array([-2.8+row*1.1,1.05-col*1.05,FLOOR])
            door=-2.2 if row<3 else 3.3
            queue=i//2;entry_start=33.0+queue*.75+(i%2)*.35 if mode=='full' else 1.0+i*.9
            start=np.array([door+(-1 if i%2 else 1)*(.7+(i%3)*.65),-3.1-(i//6)*1.1,FLOOR])
            if mode=='full' and i==10:start[0]=-4.3
            route=Route([start,[door,-2.6,FLOOR],[door,-.525,FLOOR],[slot[0],-.525,FLOOR],slot])
            if mode=='full':
                portal=1 if row<3 else 2;crossing_time=(35.8 if portal==1 else 33.0)+portal_counts[portal]*.95;portal_counts[portal]+=1
                entry_start=crossing_time-(route.cumulative[1]+.75)/1.2
            self.records.append({'id':aid,'slot':slot,'route':route,'start':entry_start,'speed':1.2,'phase':i*7,'mass':74,'door':1 if row<3 else 2})
        heroine=FilmActor(stage,cars['A']['root']+'/Passengers/heroine',cache,(.74,.48,.1),source(3));heroine.rainwear((.78,.55,.17));heroine.gull(root/'.runtime/deadweight/Deadweight_Feasibility_Assets/gull_hood.usda');self.actors['heroine']=heroine
        hero_route=Route([[-6.9,-4.4,FLOOR],[-6.3,-2.4,FLOOR],[-2.2,-2.4,FLOOR],[-2.2,-1,FLOOR],[-4.55,-1,FLOOR],[-5.05,1.0,FLOOR]])
        self.hero={'id':'heroine','slot':np.array([-5.05,.75,FLOOR]),'route':Route([*hero_route.points[:-1],[-5.05,.75,FLOOR]]),'start':27 if mode=='full' else 0,'speed':1.6,'phase':0,'mass':76,'door':1}
        self.records.append(self.hero)
        for i in range(12):
            aid=f'survivor_{i+1:02d}';actor=FilmActor(stage,cars['B']['root']+'/Passengers/'+aid,cache,self.palette[(i+2)%6],source(5+i));actor.rainwear(self.palette[(i+2)%6]);self.actors[aid]=actor
            if i==0:actor.camera_prop()
        # Frame windows are deliberately placed at matching local x positions.
        # The partner stands by the inner B window opposite the separate booth.
        self.partner=np.array([-5.05,-1.08,FLOOR])
        label(stage,'/World/Upper/LoadLabel','LOAD / HOLD',(RUN-2,-10.8,64.55),.31,(1,.64,.15))
        self.water=[]
        for i in range(18):
            water=box(stage,f'/World/Foam/Line{i}',(-8+i*.95,6,5.66),(.55,.08,.018),(.42,.68,.72),.1,.16)
            self.water.append(water.GetOrderedXformOps()[0])
        self.gait_actor=self.actors['infected_01']
        self.gait_origin=np.array([-7,-8.8,FLOOR])
        h=self.cache.heading[139];self.gait_turn=np.array([[math.cos(h),-math.sin(h),0],[math.sin(h),math.cos(h),0],[0,0,1]])
        self.gait_end=self.gait_origin+self.cache.roots[139]-self.cache.roots[0]+self.gait_turn@self.cache.displacement(250)
        # Keep the same actor continuous before and after the uncut infection.
        if mode=='full':
            # The close-up actor uses a clear back lane, then rejoins at the
            # perimeter. He takes a late front slot; its original occupant
            # boards the far slot first so nobody walks through a filled row.
            first,early=self.records[0],self.records[16]
            far=first['slot'].copy();first['slot']=early['slot'].copy();early['slot']=far
            early_start=early['route'].points[0].copy();door=-2.2
            early['route']=Route([early_start,[door,-2.6,FLOOR],[door,-.525,FLOOR],[far[0],-.525,FLOOR],far])
            early['start']=35.8-(early['route'].cumulative[1]+.75)/1.2
            first['route']=Route([[door,-2.6,FLOOR],[door,-.525,FLOOR],[first['slot'][0],-.525,FLOOR],first['slot']])
            first['start']=45-.75/1.2
        self.rejoin=Route([self.gait_end,[-5.3,self.gait_end[1],FLOOR],[-5.3,-2.4,FLOOR],self.records[0]['route'].points[0]])
        self.camera=UsdGeom.Xformable(stage.GetPrimAtPath('/World/Camera')).GetOrderedXformOps()[0]
        # Explicit low-cost sea geometry, not a fluid simulation.
        self.sea=UsdGeom.Mesh.Define(stage,'/World/WaveField')
        self.sea.CreatePointsAttr();self.sea.CreateNormalsAttr()
        self.wave_nx,self.wave_ny=240,160
        xs,ys=np.meshgrid(np.linspace(-220,270,self.wave_nx),np.linspace(-270,80,self.wave_ny));self.wave_x=xs.ravel();self.wave_y=ys.ravel()
        faces=[]
        for j in range(self.wave_ny-1):
            for i in range(self.wave_nx-1):
                v=j*self.wave_nx+i;faces.extend([v,v+1,v+self.wave_nx+1,v+self.wave_nx])
        self.sea.CreateFaceVertexCountsAttr([4]*((self.wave_nx-1)*(self.wave_ny-1)));self.sea.CreateFaceVertexIndicesAttr(faces);self.sea.CreateSubdivisionSchemeAttr('none');self.sea.CreateDisplayColorAttr([Gf.Vec3f(.035,.13,.16)]);self.sea.SetNormalsInterpolation('vertex')
        material=UsdShade.Material.Define(stage,'/World/WaveField/Material');shader=UsdShade.Shader.Define(stage,'/World/WaveField/Material/Surface');shader.CreateIdAttr('UsdPreviewSurface');shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(.025,.09,.12));shader.CreateInput('roughness',Sdf.ValueTypeNames.Float).Set(.18);shader.CreateInput('metallic',Sdf.ValueTypeNames.Float).Set(.4);material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface');UsdShade.MaterialBindingAPI.Apply(self.sea.GetPrim()).Bind(material)
        rng=np.random.default_rng(8811);self.rain_seed=np.column_stack([rng.uniform(-15,RUN+15,500),np.r_[rng.uniform(-30,-14,300),rng.uniform(-.2,.2,200)],rng.uniform(0,76,500)])
        self.rain=UsdGeom.BasisCurves.Define(stage,'/World/StormRain');self.rain.CreateTypeAttr('linear');self.rain.CreateCurveVertexCountsAttr([2]*500);self.rain.CreateWidthsAttr([.0025]);self.rain.SetWidthsInterpolation('constant');self.rain.CreateDisplayColorAttr([Gf.Vec3f(.38,.53,.59)])
        self.rain.CreatePointsAttr()

    def position_car(self,t):
        if self.mode=='passing':
            # Explicit preloaded shot rehearsal; does not provide boarding proof.
            u=np.clip((t-49)/34,0,1);u=u**3*(10+u*(-15+6*u));state={'upper_s_m':112*u,'lower_s_m':112*(1-u),'moving':0<u<1}
        else:state=self.dispatch.advance(t)
        progress=state['upper_s_m']/112
        self.car_positions={'A':np.array([RUN*(1-progress),-2.4,59-56*progress]),'B':np.array([RUN*progress,2.4,3+56*progress])}
        for name,car in self.cars.items():car['xform'].Set(Gf.Vec3d(*map(float,self.car_positions[name])))
        return state

    def follow_route(self,record,t):
        route=record['route'];elapsed=max(0,t-record['start']);distance=min(route.length,elapsed*record['speed'])
        brake=.5;entry=max(0,route.length-record['speed']*brake/2);brake_start=entry/record['speed']
        if elapsed>brake_start:
            u=float(np.clip((elapsed-brake_start)/brake,0,1));distance=entry+(route.length-entry)*(2*u-u*u)
        position,heading=route.at(distance)
        if distance>=route.length-1e-6:
            heading=math.pi/2 if record['id']=='heroine' else math.pi/2+.08*math.sin(record['phase'])
            if record['id'] not in self.arrivals:self.arrivals[record['id']]=t
        return position,heading,distance

    def observe(self,aid,position,car,action):
        actor=self.actors[aid]
        rz=np.array(actor.matrix)[:3,:3]
        toes=[actor.joint_p[self.cache.index(n)]@rz for n in ['L_ToeBase','R_ToeBase']]
        intended=self.car_positions[car]+position
        world=np.array(UsdGeom.XformCache().GetLocalToWorldTransform(self.stage.GetPrimAtPath(actor.path)).ExtractTranslation())
        if np.linalg.norm(world-intended)>1e-6:raise RuntimeError('competing root controller or invalid cabin parent transform')
        return {'actor_id':aid,'controller':'cinematic_full_pose_cache','action':action,'car':car,'local_root_m':position.tolist(),'position_m':world.tolist(),'toe_height_over_floor_m':[float(v[2]+position[2]-FLOOR) for v in toes],'toes_world_m':[(v+world).tolist() for v in toes]}

    def boarding(self,record,t,position,obs):
        aid=record['id'];slot=record['slot'];arrived=float(np.linalg.norm(position-slot))<.03
        previous=self.stable.get(aid)
        feet=all(-.05<=z<=.25 for z in obs['toe_height_over_floor_m'])
        if not arrived or not feet:self.stable.pop(aid,None);return
        if previous is None:self.stable[aid]=t;return
        if self.dispatch.departure_s is None:
            accepted=self.dispatch.observe_boarding(aid,aid+'_slot',record['mass'],inside=arrived,feet_supported=feet,stable_s=t-previous,speed_mps=0,sim_time=t)
            if accepted:self.boarded.append(aid)

    def aim(self,eye,target,lens):
        self.camera.Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float,eye)),Gf.Vec3d(*map(float,target)),Gf.Vec3d(0,0,1)).GetInverse());self.stage.GetPrimAtPath('/World/Camera').GetAttribute('focalLength').Set(float(lens))

    def update(self,t):
        state=self.position_car(t);observations=[]
        stop_time=(self.dispatch.departure_s if self.dispatch.departure_s is not None else 49)+34
        for record in self.records:
            aid=record['id'];actor=self.actors[aid];position,heading,distance=self.follow_route(record,t)
            if self.mode=='passing':position=record['slot'].copy();distance=record['route'].length
            phase=self.cache.phase_at_distance(distance+self.cache.displacement(record['phase'])[0])
            if aid=='heroine':
                p,q=self.cache.pose(distance/1.2*38,'walk' if distance<record['route'].length and t>=record['start'] else 'idle')
                gesture=smooth((t-58)/3)*(1-smooth((t-71)/2))
                if 27<t<30 and self.mode=='full':gesture=.55
                p,q=raised_wings(self.cache,p,q,gesture*.68,('L',))
                if t>=stop_time:
                    u=smooth((t-stop_time-.4)/2.2);position=np.array([-5.05,.75-5.5*u,FLOOR]);heading=math.pi/2-math.pi*smooth((t-stop_time)/.4)
                    p,q=self.cache.pose(u*5.5/1.2*38,'walk')
            elif t<record['start'] and self.mode=='full':
                infection=14+(int(aid[-2:])%6)*.5
                p,q=infected_wait(self.cache,record['phase']+(t-infection)*12,smooth((t-infection)/.75))
            else:p,q=self.cache.pose(phase)
            if aid=='infected_01' and self.mode=='full' and t<record['start']:
                f=max(0,(t-14)*30)
                if t<14:
                    position=self.gait_origin.copy();p,q=self.cache.pose(0,'idle');heading=self.cache.heading[0]
                elif f<140:
                    i=min(139,int(f));p=self.cache.p[i];q=self.cache.q[i];position=self.gait_origin+(self.cache.roots[i]-self.cache.roots[0]);heading=self.cache.heading[i]
                elif t<27:
                    p,q=self.cache.pose(f-140);heading=self.cache.heading[139];delta=self.cache.displacement(f-140)
                    turn=np.array([[math.cos(heading),-math.sin(heading),0],[math.sin(heading),math.cos(heading),0],[0,0,1]])
                    position=self.gait_origin+(self.cache.roots[139]-self.cache.roots[0])+turn@delta
                else:
                    travelled=self.rejoin.length*np.clip((t-27)/(record['start']-27),0,1)
                    position,heading=self.rejoin.at(travelled);p,q=self.cache.pose(250+travelled/self.cache.travel[-1,0]*self.cache.period)
            if aid!='heroine' and distance>=record['route'].length:
                p,q=torso_sway(self.cache,p,q,.045*math.sin(t*1.7+record['phase']))
            actor.update(p,q,position,heading)
            obs=self.observe(aid,position,'A','gull' if aid=='heroine' else 'zombie');observations.append(obs)
            if self.mode!='passing':self.boarding(record,t,position,obs)
        for i in range(12):
            aid=f'survivor_{i+1:02d}';actor=self.actors[aid]
            position=self.partner.copy() if i==0 else np.array([-2.8+(i-1)%4*2.1,-.8+(i-1)//4*.85,FLOOR])
            heading=-math.pi/2
            p,q=self.cache.pose(0,'idle')
            p,q=torso_sway(self.cache,p,q,.012*math.sin(t*1.3+i*2))
            if i==0:p,q=raised_wings(self.cache,p,q,.80*smooth((t-57)/3)*(1-smooth((t-71)/2)),('R',))
            actor.update(p,q,position,heading);observations.append(self.observe(aid,position,'B','survivor'))
        closing=smooth((t-48)/1) if self.mode=='full' else smooth((t-10)/1)
        for name,car in self.cars.items():
            for key,op in car['doors'].items():
                open_amount=1-closing
                if key=='inner':open_amount=1-smooth((t-(34 if self.mode=='full' else 7))/.6)
                if key==0:open_amount=smooth((t-stop_time)/.5) if name=='A' else 1-closing
                if name=='B' and t>=stop_time:open_amount=smooth((t-stop_time)/.6)
                op.Set(Gf.Vec3d(0,0,2.6*open_amount) if key=='inner' else Gf.Vec3d(1.85*open_amount,0,0))
        self.dispatch.upper_closed=all(abs(self.cars['A']['doors'][i].Get()[0])<1e-8 for i in [1,2])
        self.dispatch.lower_closed=all(abs(self.cars['B']['doors'][i].Get()[0])<1e-8 for i in [1,2])
        self.dispatch.booth_closed=abs(self.cars['A']['doors']['inner'].Get()[2])<1e-8 and abs(self.cars['A']['doors'][0].Get()[0])<1e-8
        self.dispatch.driver_release=t>=(49 if self.mode=='full' else 11)
        for i,op in enumerate(self.water):
            y=6+1.5*math.sin(t*1.4+i*.3);op.Set(Gf.Vec3d(-8+i*.95,y,5.66+.008*math.sin(t+i)))
        z=.23*np.sin(self.wave_x*.27+self.wave_y*.18-t*1.9)+.12*np.sin(self.wave_x*.51-self.wave_y*.32+t*1.1)-.1
        self.sea.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(np.column_stack([self.wave_x,self.wave_y,z]).astype(np.float32)))
        first=np.cos(self.wave_x*.27+self.wave_y*.18-t*1.9);second=np.cos(self.wave_x*.51-self.wave_y*.32+t*1.1)
        normals=np.column_stack([-.23*.27*first-.12*.51*second,-.23*.18*first+.12*.32*second,np.ones_like(first)]);normals/=np.linalg.norm(normals,axis=1)[:,None];self.sea.GetNormalsAttr().Set(Vt.Vec3fArray.FromNumpy(normals.astype(np.float32)))
        drops=self.rain_seed.copy();drops[:,2]=np.mod(drops[:,2]-t*18,76)
        tips=drops+np.array([.15,0,-.8]);self.rain.GetPointsAttr().Set(Vt.Vec3fArray.FromNumpy(np.stack([drops,tips],axis=1).reshape(-1,3).astype(np.float32)))
        self.frame_camera(t,observations)
        return observations,state

    def frame_camera(self,t,observations):
        a=self.car_positions['A'];b=self.car_positions['B'];hero=np.array(next(o for o in observations if o['actor_id']=='heroine')['position_m'])+np.array([0,0,1.35])
        if self.mode=='boarding':
            target=a+np.array([-.5,-2,FLOOR+.9]);self.aim(target+np.array([-2,-17,4]),target,38);return
        if self.mode=='passing':
            # Trackside camera sees both inward-facing windows, face and wings.
            target=(a+b)/2+np.array([-5.05,0,FLOOR+1.25]);self.aim(target+np.array([-4.7,0,1.0]),target,36);return
        if t<6:
            target=np.array([RUN*.43,0,32]);self.aim(target+np.array([-45+4*t,-126+3*t,52-2*t]),target,37)
        elif t<10:
            target=b+np.array([-2,.1,FLOOR+1]);self.aim(target+np.array([3,8,1.2]),target,45)
        elif t<12:
            target=np.array([RUN+6.8,-10,63.5]);self.aim(target+np.array([-2,-4,1.2]),target,42)
        elif t<14:
            self.aim(hero+np.array([-2,-6,1]),hero,55)
        elif t<27:
            target=np.array(observations[0]['position_m'])+np.array([0,0,.85]);self.aim(target+np.array([1.8,-6,1.2]),target,45)
        elif t<30:
            target=np.array([RUN-7,-8,63]);self.aim(target+np.array([-3,-7,1.7]),target,43)
        elif t<36:
            target=np.array(next(o for o in observations if o['actor_id']=='heroine')['position_m'])+np.array([0,0,1.1]);self.aim(target+np.array([-3,-6.5,1.5]),target,43)
        elif t<43:
            target=a+np.array([.5,-.2,FLOOR+1]);self.aim(target+np.array([2,-13,4]),target,38)
        elif t<49:
            target=a+np.array([1,-1,FLOOR+.85]);self.aim(target+np.array([-2,-8,1.3]),target,42)
        elif t<59:
            target=np.array([RUN*.5,0,32]);self.aim(target+np.array([-35,-136,47]),target,35)
        elif t<63:
            target=b+np.array([-4,-.4,FLOOR+1.2]);self.aim(target+np.array([1.5,4,.4]),target,43)
        elif t<69:
            target=(a+b)/2+np.array([-5.05,0,FLOOR+1.25]);self.aim(target+np.array([-4.7,0,1.0]),target,36)
        elif t<74:
            self.aim(hero+np.array([-3,5,1.3]),hero,48)
        elif t<80:
            target=(a+b)/2+np.array([0,0,FLOOR]);self.aim(target+np.array([-37,-111,45]),target,36)
        elif t<86:
            self.aim(a+np.array([-10,-12,FLOOR+4]),a+np.array([-5,-1.5,FLOOR+1]),43)
        else:
            target=np.array([RUN*.5,0,32]);self.aim(target+np.array([-40,-120,48]),target,35)

    def result(self):
        return {'scope':'Cinematic skeletal-cache boarding/transport; not Native navigation or railway physics.',
                'actors':len(self.actors),'infected':self.count,'boarded_ids':self.boarded,'load_kg':self.dispatch.load_kg,
                'departure_s':self.dispatch.departure_s,'events':self.dispatch.events,'arrivals':self.arrivals,
                'slot_min_distance_m':float(min(np.linalg.norm(a['slot']-b['slot']) for i,a in enumerate(self.records) for b in self.records[i+1:]))}
