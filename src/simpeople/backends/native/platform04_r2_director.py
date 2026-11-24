"""R2 film performances: identity tests and a committed, visibly missed attack."""
import json,math
from pathlib import Path
import numpy as np
from pxr import UsdGeom,UsdLux,Gf
from .performance_score import DoorScore,SameDirectionScore,Trajectory,smooth,window
from .platform04_r2_motion import PerformanceMotion,PerformanceActor,PerformanceLayer,bend_fingers
from .platform04_90_scene import ShoulderBag
from .platform04_scene import aim
from .platform04_animation import axis_q,rotate_branch,reach
from .deadweight_set import box
from .sole_floor import SoleFloor


def audition_scene(stage):
    UsdGeom.Xform.Define(stage,'/World');stage.SetDefaultPrim(stage.GetPrimAtPath('/World'));UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z');stage.SetTimeCodesPerSecond(30)
    box(stage,'/World/Floor',(20,0,-.08),(100,70,.16),(.31,.34,.35),0,.8)
    for i,x in enumerate(np.arange(-20,65,.5)):box(stage,f'/World/Grid/X{i}',(x,0,.001),(.009,70,.002),(.24,.27,.28),0,.9)
    for i,y in enumerate(np.arange(-15,25,.5)):box(stage,f'/World/Grid/Y{i}',(20,y,.001),(100,.009,.002),(.24,.27,.28),0,.9)
    dome=UsdLux.DomeLight.Define(stage,'/World/Dome');dome.CreateIntensityAttr(650)
    sun=UsdLux.DistantLight.Define(stage,'/World/Sun');sun.CreateIntensityAttr(1500);sun.AddRotateXYZOp().Set(Gf.Vec3f(25,-30,-20))
    camera=UsdGeom.Camera.Define(stage,'/World/Camera');camera.AddTransformOp();camera.CreateHorizontalApertureAttr(36);camera.CreateVerticalApertureAttr(20.25);camera.CreateClippingRangeAttr(Gf.Vec2f(.05,180))


class R2Director:
    def __init__(self,stage,scene,root,out,mode='trio',case='human_fast',angle='side',body=0,camera='new'):
        self.stage=stage;self.scene=scene;self.root=Path(root);self.out=Path(out);self.mode=mode;self.case=case;self.angle=angle;self.body=body;self.camera=camera;self.bank=PerformanceMotion(root);self.actors={};self.bags={};self.layers={};self.score=SameDirectionScore() if mode=='parallel' else DoorScore();self.actor_state={};self.floor=SoleFloor(scene.get('boxes',[]))
        if mode=='identity':ids=['F02' if 'infected' in case else 'H01']
        elif mode=='trio':ids=['H01','F02','F01']
        else:ids=['H01','F02']
        assets=json.loads((self.root/'configs/assets.json').read_text())['assets']
        for aid in ids:
            index=body if mode=='identity' else {'H01':0,'F02':3,'F01':9}[aid];asset=assets[index];source=self.root/'assets/characters'/asset['source_uri'].removeprefix('characters://');color=(.31,.32,.32) if mode=='identity' else {'H01':(.78,.45,.06),'F02':(.54,.035,.025),'F01':(.59,.61,.57)}[aid];actor=PerformanceActor(stage,'/World/Cast/'+aid,self.bank,color,str(source));self.actors[aid]=actor
            for clip in ['idle','walk','final','zslow']:actor.fit(clip)
            actor.calibrate_soles();self.layers[aid]=PerformanceLayer(self.bank,actor,self.score,aid)
            if self.layers[aid].feet:self.floor.set_phrase(self.layers[aid].feet)
            if aid=='H01' and mode!='identity':self.bags[aid]=ShoulderBag(stage,actor,(.63,.39,.065))
        self.duration=5. if mode=='identity' else 10.
        self.identity_start=3.0 if 'human' in case else 2.5
        self.slow_paths={
            'H01':Trajectory([(0,(0,0),(.65,0)),(1.8,(1.17,0),(.65,0)),(2.2,(1.30,.03),(0,0)),(2.8,(1.30,.35),(.15,.4)),(5,(2.7,.75),(.70,0))]),
            'F02':Trajectory([(0,(0,0),(.60,0)),(1.3,(.78,0),(.60,0)),(1.6,(.88,0),(0,0)),(2.5,(1.43,.30),(.75,.2)),(3.7,(2.15,.50),(.2,0)),(5,(2.25,.5),(0,0))])}
        self.slow_tables={}
        for aid,path in self.slow_paths.items():
            ts=np.linspace(0,5,1001);xy=np.array([path.sample(t)[0] for t in ts]);self.slow_tables[aid]=(ts,np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))])
        (self.out/'casting.json').write_text(json.dumps({'mode':mode,'case_private':case,'actor_ids':ids,'same_model_neutral_no_props':mode=='identity','body_asset_index':body if mode=='identity' else None,'root_owner':'R2 authored trajectory only; no original XY root motion added','autonomous_infection_pursuit':False,'contact_model':'authored foot support targets + fixed bone IK; no contact-force solver'},indent=2))
        (self.out/'event_score.json').write_text(json.dumps({'events':self.score.events,'committed_target_m':self.score.committed_target.tolist(),'scope':'author-designed film score; never inferred autonomous agent behavior'},indent=2))
        (self.out/'authored_support_windows.json').write_text(json.dumps({aid:{side:[{**s,'anchor':s['anchor'].tolist()} for s in slots] for side,slots in layer.feet.slots.items()} for aid,layer in self.layers.items() if layer.feet},indent=2))

    def slow_pose(self,aid,t):
        b=self.bank;a=self.actors[aid];path=self.slow_paths[aid];xy,v=path.sample(t);yaw=math.atan2(v[1],v[0]) if np.linalg.norm(v)>.03 else 0.;ts,ds=self.slow_tables[aid];distance=float(np.interp(t,ts,ds));clip='walk' if aid=='H01' else 'zslow';phase=a.phase(distance,clip);p,q=b.pose(phase,clip);lift=a.ground_lift(clip,phase)
        if aid=='H01':
            greeting=window(t,1.9,3.25,.20);p,q=b.glance(p,q,.75*greeting);target=reach(b,p,q,'L',[.22,.30,1.34]);p,q=b.mix((p,q),target,.85*greeting)
            p,q=rotate_branch(b,p,q,'Spine02',axis_q([0,0,1],.16*greeting))
            state='walk' if t<1.8 else 'notice_companion_yield' if t<3.1 else 'resume_toward_companion'
        else:
            lock=window(t,1.35,3.85,.14);p,q=b.glance(p,q,.65*lock);p,q=rotate_branch(b,p,q,'Spine02',axis_q([0,0,1],.18*smooth((t-1.65)/.4)))
            grab=window(t,2.25,3.7,.18);target=reach(b,p,q,'R',[.61,-.17,1.13]);p,q=b.mix((p,q),target,grab);p,q=bend_fingers(b,p,q,'R',.75*grab);p,q=rotate_branch(b,p,q,'JawRoot',axis_q([0,1,0],.13*lock));state='wandering' if t<1.35 else 'stimulus_takes_attention' if t<2.25 else 'reach_past_target' if t<3.9 else 'search_after_miss'
        return xy,yaw,float(np.linalg.norm(v)),(p,q),lift,{},phase,state

    def update(self,f):
        t=float(f)/30.;virtual=t+self.identity_start if self.mode=='identity' and 'fast' in self.case else t;result={'source_tick':f,'story_time_s':53+t if self.mode!='identity' else None,'mode':self.mode,'shot':'R2_'+self.mode,'actors':{},'events':[e for e in self.score.events if t-1/30<e['t']<=t]}
        for aid,a in self.actors.items():
            if self.mode=='identity' and 'slow' in self.case:xy,yaw,speed,pose,lift,ledger,phase,state=self.slow_pose(aid,t);weight=0.
            else:
                xy,yaw,speed=self.score.root(aid,virtual);pose,lift,ledger,weight,phase=self.layers[aid].evaluate(virtual);state=self.score.state(aid,virtual)
            if 'injured' in self.case and self.mode=='identity':pose=self.bank.mix(pose,reach(self.bank,*pose,'R',[.08,-.14,1.05]),.85)
            a.safe_update(pose,[*xy,0],yaw,lift);m=np.asarray(a.matrix);shoe=np.concatenate(list(a.foot_points().values()));world_shoe=shoe@m[:3,:3]+m[3,:3];adjust=self.floor.correction(world_shoe)
            if adjust>.15:raise ValueError(f'R2 source feet too deep {aid}: {adjust}')
            if adjust:lift+=adjust;a.safe_update(pose,[*xy,0],yaw,lift)
            sole_points=a.soles_world()
            for side,entry in ledger.items():entry['actual_point_world_m']=sole_points[side].tolist()
            # A bag is briefly protected during detection; both arms are free
            # again for the resumed escape rather than staying stuck on it.
            if aid in self.bags:
                for updater in a.props:updater(a)
            result['actors'][aid]={'root_world_m':[*xy,0],'yaw_rad':yaw,'speed_mps':speed,'phase':phase,'gait':'authored_phrase' if weight>.5 else 'zslow' if 'slow' in self.case and aid=='F02' else 'walk' if 'slow' in self.case else 'final','behavior':state,'state':state,'support':ledger,'ground_adjustment_m':adjust,'foot_phrase_weight':weight,'committed_target_m':self.score.attack_target(virtual).tolist() if aid=='F02' and self.score.attack_target(virtual) is not None else None,'root_owner':'R2 film trajectory','identity_start_s':self.identity_start if self.mode=='identity' else None}
        self.set_camera(t,result)
        camera=self.stage.GetPrimAtPath('/World/Camera');result['camera_matrix']=np.asarray(UsdGeom.Xformable(camera).GetOrderedXformOps()[0].Get()).tolist();result['camera_focal_mm']=float(camera.GetAttribute('focalLength').Get());self.actor_state=result;return result

    def set_camera(self,t,row):
        if self.mode=='identity':
            xy=np.array(next(iter(row['actors'].values()))['root_world_m']);offset=[0,5.3,1.25] if self.angle=='side' else [4.0,4.0,1.35];aim(self.stage,(xy+offset).tolist(),(xy+[0,0,.92]).tolist(),48 if self.angle=='side' else 45);return
        if self.camera=='full':
            aim(self.stage,[23.0,10.0,2.0],[21.5,.8,.9],70);return
        hero=np.array(row['actors']['H01']['root_world_m']);red=np.array(row['actors']['F02']['root_world_m']);pre=smooth((t-2.0)/2.2);eye=np.array([hero[0]+1.8,6.2,1.40])*(1-pre)+np.array([26.8,7.8,1.50])*pre;eye[2]+=1.3*smooth((t-6.8)/.9);target=.55*hero+.45*red+[0,0,1.0]
        pan=smooth((t-7.0)/1.3);target=target*(1-pan)+(hero+[0,0,1.0])*pan
        late=smooth((t-7.7)/2.3);eye=eye*(1-late)+(hero+[4.0,-2.0,1.80])*late;aim(self.stage,eye.tolist(),target.tolist(),64)
