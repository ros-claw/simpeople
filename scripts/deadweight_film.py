"""Deadweight film rehearsals, separate from the completed Shift Change film.

All passenger playback is explicitly a cinematic skeletal cache, not Native
navigation or PhysX passenger transport. Behavior capture is a separate run.
"""
import argparse,json,os,sys,time,shutil,math,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
parser=argparse.ArgumentParser();parser.add_argument('--run-id',required=True);parser.add_argument('--gpu',type=int,default=3);parser.add_argument('--shot',choices=['gait','boarding','passing','full'],default='gait');parser.add_argument('--frames',type=int);parser.add_argument('--start-time',type=float);args=parser.parse_args()
directory=ROOT/'runs'/args.run_id;directory.mkdir(parents=True,exist_ok=False)
(directory/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}))
for name in ['scripts/deadweight_film.py','src/simpeople/backends/native/deadweight_cinema.py','src/simpeople/backends/native/deadweight_set.py','src/simpeople/backends/native/deadweight_director.py','src/simpeople/core/deadweight.py']:
    target=directory/'source_snapshot'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True})
recorder=None;exit_code=0
try:
    import omni.usd,omni.timeline
    import numpy as np
    from pxr import UsdGeom,Gf
    from simpeople.backends.native.recording import Recorder
    from simpeople.backends.native.deadweight_cinema import FilmActor,FilmPoseCache
    from simpeople.backends.native.deadweight_set import create_set,RUN,FLOOR
    omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage()
    cars=create_set(stage,ROOT)
    cache=FilmPoseCache(ROOT/'runs/deadweight-zombie-probe-05')
    inputs={}
    for name in ['cache_rig.json','native_bones.npz','zombie_frames.jsonl']:
        source=ROOT/'runs/deadweight-zombie-probe-05'/name;target=directory/'source_snapshot'/'pose_cache'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);inputs[str(source)]=hashlib.sha256(source.read_bytes()).hexdigest()
    (directory/'input_hashes.json').write_text(json.dumps(inputs,indent=2))
    (directory/'pose_cache_scope.json').write_text(json.dumps(cache.report(),indent=2))
    for name,car in cars.items():
        car['xform'].Set(Gf.Vec3d(RUN if name=='A' else 0,-2.4 if name=='A' else 2.4,59 if name=='A' else 3))
        for k,op in car['doors'].items():op.Set(Gf.Vec3d(0,0,3) if k=='inner' else Gf.Vec3d(1.85,0,0))
    print('Creating film actor',flush=True)
    actor=FilmActor(stage,'/World/Actors/tourist_01',cache,(.38,.45,.33)) if args.shot=='gait' else None
    print('Film actor ready',flush=True)
    timeline=omni.timeline.get_timeline_interface();timeline.set_auto_update(False);timeline.set_time_codes_per_second(30);timeline.set_end_time(1000);timeline.play();timeline.commit()
    camera=UsdGeom.Xformable(stage.GetPrimAtPath('/World/Camera')).GetOrderedXformOps()[0]
    def aim(eye,target,lens=45):
        camera.Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*map(float,eye)),Gf.Vec3d(*map(float,target)),Gf.Vec3d(0,0,1)).GetInverse());stage.GetPrimAtPath('/World/Camera').GetAttribute('focalLength').Set(lens)
    frames=args.frames or {'gait':390,'boarding':360,'passing':450,'full':2640}[args.shot]
    origin=np.array([RUN-5,-7.2,59+FLOOR])
    def update(frame):
        if frame<140:
            i=min(frame,len(cache.p)-1);p=cache.p[i];q=cache.q[i];heading=cache.heading[i]
            root=origin+cache.roots[i]-cache.roots[0]
        else:
            f=frame-140;p,q=cache.pose(f);heading=cache.heading[139]
            turn=np.array([[math.cos(heading),-math.sin(heading),0],[math.sin(heading),math.cos(heading),0],[0,0,1]])
            root=origin+cache.roots[139]-cache.roots[0]+turn@cache.displacement(f)
        actor.update(p,q,root,heading)
        aim(root+np.array([1.6,-5.8,2.0]),root+np.array([0,0,.85]),48)
        return [{'actor_id':'tourist_01','controller':'cinematic_full_pose_cache','position_m':root.tolist(),'action':'walk' if frame<90 else 'zombie'}]
    director=None
    if args.shot!='gait':
        from simpeople.backends.native.deadweight_director import DeadweightDirector
        director=DeadweightDirector(stage,cars,cache,ROOT,args.shot)
        def update(frame):
            t=(args.start_time if args.start_time is not None else 49 if args.shot=='passing' else 0)+frame/30
            observations,state=director.update(t)
            return observations
    print('Initializing pose',flush=True)
    update(0);print('Creating recorder',flush=True);recorder=Recorder(directory,(1920,1080),gpu_index=args.gpu)
    for _ in range(5):recorder.step(0)
    recorder.control({'mode':'start'});log=(directory/'frames.jsonl').open('w')
    for frame in range(frames):
        wall=time.monotonic();observations=update(frame);recorder.step(1/30)
        if frame%90==0:print(f'captured {frame}/{frames}',flush=True)
        identity={'source_tick':frame,'movie_time_s':frame/30,'shot':args.shot,'story_time_s':(args.start_time if args.start_time is not None else 49 if args.shot=='passing' else 0)+frame/30}
        recorder.capture(timeline.get_current_time(),identity)
        apparatus={'cars_world_m':{k:list(v['xform'].Get()) for k,v in cars.items()},'contacts':{'upper':director.dispatch.upper_closed,'lower':director.dispatch.lower_closed,'booth':director.dispatch.booth_closed},'driver_release':director.dispatch.driver_release,'load_kg':director.dispatch.load_kg} if director else {}
        log.write(json.dumps({**identity,'sim_time_s':timeline.get_current_time(),'wall_step_s':time.monotonic()-wall,'camera_matrix':list(map(list,camera.Get())),'actors':observations,**apparatus})+'\n')
        if frame in [0,89,120,200,300,419,510,600,780,810,900,960,1020,1080,1200,1320,1440,1470,1530,1650,1770,1860,1920,1970,1980,1990,2010,2070,2250,2400,2490,2550,2570,frames-1]:
            from PIL import Image
            Image.fromarray(np.asarray(recorder.rgb.get_data(device='cpu'))[:,:,:3]).save(directory/f'frame_{frame:04d}.png')
    log.close();recorder.close();recorder=None
    result=director.result() if director else {}
    (directory/'completed.json').write_text(json.dumps({'frames':frames,'scope':'Isaac 6.2 RGB, cinematic skeleton playback. Native source run is deadweight-zombie-probe-05. Not Native navigation/ride.',**result},indent=2))
except Exception:
    import traceback
    traceback.print_exc();(directory/'failed.txt').write_text(traceback.format_exc());exit_code=1
finally:
    if recorder:recorder.close()
    app.close()
raise SystemExit(exit_code)
