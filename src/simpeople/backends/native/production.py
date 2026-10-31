"""One main-thread film director; people continue to use the native supervisor."""
from collections import Counter
import json
from pathlib import Path
import time
from pxr import Gf, UsdGeom
from simpeople.core.cinema import CinematicCamera


HEROES = ('patrol_orange', 'patrol_blue')


def move(target, gait='walk'):
    return {'action': 'move_to', 'target': target, 'gait': gait, 'timeout_s': 180}


def wait(seconds):
    return {'action': 'wait', 'duration_s': max(.01, seconds)}


class ShiftChangeDirector:
    def __init__(self, engine, config, directory):
        self.e, self.config, self.directory = engine, config, Path(directory)
        self.mode = config['mode']
        self.frames = {'technical': 900, 'director': 720, 'master': 2700}[self.mode]
        if config.get('fps')!=30 or config.get('frames')!=self.frames:raise ValueError('production frame count/fps do not match the selected mode')
        self.camera = CinematicCamera(self.mode)
        self.log = (self.directory / 'cinematic_frames.jsonl').open('w', buffering=1)
        self.programs = {}
        self.scheduled = set()
        self.command_baseline = None
        self.command_tasks = None
        self.command_wait_wall = None
        self.last_shot = None
        self.previous_pose = None
        self.request_serial = 0
        self.cast = []
        self.spawn_cast()
        self.directory.joinpath('cinematic_cast.json').write_text(json.dumps(self.cast, indent=2))

    def submit(self, aid, steps):
        self.request_serial += 1
        return self.e.cmd_run_activity({'request_id': f'film-{self.request_serial}', 'actor_id': aid, 'steps': steps}, source='scheduler')

    def spawn(self, aid, asset, role, position, steps, repeat=False):
        self.e.cmd_spawn({'actor_id': aid, 'asset_id': asset, 'role': role, 'group': 'shift_change', 'spawn_anchor': position})
        self.cast.append({'actor_id': aid, 'asset_id': asset, 'role': role, 'spawn_m': position})
        self.submit(aid, steps)
        if repeat:
            self.programs[aid] = steps

    def spawn_cast(self):
        orange = 'male_adult_construction_02_accent'
        blue = 'male_adult_construction_03_accent'
        if self.mode == 'technical':
            self.spawn('patrol_orange', orange, 'patrol', [-12.5, -5, 0], [move([2.5,-5,0]),wait(120)])
            return
        master = self.mode == 'master'
        for aid, asset, x in [(HEROES[0], orange, 2.5), (HEROES[1], blue, 5)]:
            lane=-5 if x==2.5 else -3.75
            stage_x=11.25 if x==2.5 else 13.75
            start = [-7.5 if x==2.5 else -10,lane,0] if master else [stage_x,lane,0]
            steps = [move([x,lane,0]),move([stage_x,lane,0]),wait(600)] if master else [wait(600)]
            self.spawn(aid, asset, 'patrol', start, steps)
        self.spawn('bench_waiter', 'female_adult_business_02', 'visitor', [8.75,-10.75,0], [wait(600)])
        self.spawn('seat_actor', 'female_adult_medical_01', 'rest', [7.5,-11.25,0], [wait(600)])
        self.spawn('jogger', 'female_adult_police_03', 'runner', [1.25,-6.25,0], [wait(600)])
        for i in range(6):
            x = [-17.5,-12.5,-8.75,-6.25,10,18.75][i]
            home=[x,-20,0]
            goal=[[-16.25,5],[-11.25,10],[-8.75,5],[-5,11],[10,10],[18.75,10]][i]+[0]
            asset=['default','male_adult_medical_01','female_adult_business_02_accent',
                   'female_adult_police_01','male_adult_construction_05','female_adult_police_02'][i]
            self.spawn(f'commuter_{i:02d}',asset,'commuter',home,[wait(i*.7),move(goal),wait(4+i),move(home),wait(2)],True)
        for i in range(2):
            start=[-18.75+i*2.5,0,0]
            self.spawn(f'patrol_{i+2:02d}','male_adult_police_04' if i else 'female_adult_police_02_accent','patrol',start,
                       [move([start[0],16.25,0]),move([12.5-i*2.5,16.25,0]),wait(3),move(start)],True)
        for i in range(2):
            start=[-18.75+i*2.5,-10,0]
            self.spawn(f'visitor_{i+1:02d}','female_adult_business_02_accent' if i else 'male_adult_medical_01_accent','visitor',start,
                       [move([-12.5+i*3.75,0,0]),wait(7),move(start),wait(2)],True)
        for i in range(2):
            self.spawn(f'rest_{i+1:02d}','male_adult_construction_01' if i else 'female_adult_police_01','rest',
                       [11.25+i*3.75,-15,0],[{'action':'sit','target':f'seat_{i+4:02d}','duration_s':55},
                                               {'action':'leave_seat'},wait(8)],True)
        for i in range(3):
            home=[-8.75+i*1.25,-6.25-i*1.25,0]
            self.spawn(f'queue_{i:02d}',['male_adult_construction_05_accent','female_adult_medical_01_accent','male_adult_police_04_accent'][i],
                       'queue',home,[wait(i*2),{'action':'queue','target':'production_queue','duration_s':9},move(home),wait(3)],True)
        self.spawn('runner_01','default_accent','runner',[-18.75,17.5,0],
                   [move([18.75,17.5,0],'run'),wait(3),move([-18.75,17.5,0],'run'),wait(4)],True)
        for i in range(3):
            home=[[-15,1.25,0],[-2.5,0,0],[15,1.25,0]][i]
            self.spawn(f'responder_{i:02d}',['male_adult_construction_03','female_adult_police_02','male_adult_construction_01_accent'][i],
                       'responder',home,[wait(6+i*3),move([home[0],5,0]),wait(5),move(home)],True)
        assert len(self.cast)==24 and len(Counter(a['role'] for a in self.cast))==7

    def nav_check(self):
        rows=[]
        backend=self.e.backend
        for actor in self.cast:
            start=actor['spawn_m']
            point=backend.segment(start,start)
            rows.append({'actor_id':actor['actor_id'],'kind':'spawn','reachable':bool(point)})
        for target in ['B1','B2','A1','A2']:
            end=backend.resolve_target(target)
            path=backend.segment([5,-11.25,0],end)
            rows.append({'target':target,'kind':'story_route','reachable':bool(path),'navmesh_points':len(path or [])})
        self.directory.joinpath('cinematic_navigation.json').write_text(json.dumps(rows,indent=2))
        if not all(row['reachable'] for row in rows):
            raise RuntimeError('production cast or target lacks a valid NavMesh route')

    def states(self):
        return {aid:{'task_id':a['task_id'],'control_epoch':a['control_epoch'],
                     'task':self.e.public(self.e.tasks[a['task_id']]) if a['task_id'] else None}
                for aid,a in self.e.actors.items()}

    def before_step(self, frame):
        e=self.e
        t=frame/30
        if not e.paused:
            for aid,steps in self.programs.items():
                task=e.tasks[e.actors[aid]['task_id']]
                if task['status'] in {'succeeded','failed','cancelled'}:
                    self.submit(aid,steps)
            triggers=([('tech_hold',10),('tech_return',20)] if self.mode=='technical' else
                      [('old_a',40 if self.mode=='master' else 4),('sit',20 if self.mode=='master' else 1),
                       ('jog',32 if self.mode=='master' else 3)])
            for name,at in triggers:
                if name in self.scheduled or t<at:
                    continue
                self.scheduled.add(name)
                if name=='old_a':
                    for n,aid in enumerate(HEROES,1):
                        lane=-5 if n==1 else -3.75
                        self.submit(aid,[move([1.25,lane,0]),move(f'A{n}'),wait(600)])
                elif name=='sit':
                    self.submit('seat_actor',[{'action':'sit','target':'seat_00','duration_s':7},
                                              {'action':'leave_seat'},wait(600)])
                elif name=='jog':self.submit('jogger',[move([18.75,-6.25,0],'run'),wait(600)])
                elif name=='tech_hold':self.submit('patrol_orange',[wait(600)])
                elif name=='tech_return':self.submit('patrol_orange',[move([-12.5,-5,0]),wait(600)])
        trigger=44 if self.mode=='master' else 8
        if self.mode!='technical' and t>=trigger and self.command_baseline is None:
            self.command_baseline=self.states();self.command_wait_wall=time.time()
            e.cmd_pause({})
            e.backend.timeline.commit()
            self.command_sim_time=e.sim_time
            self.directory.joinpath('cinematic_command_ready.json').write_text(json.dumps({
                'frame':frame,'sim_time':e.sim_time,'wall_time':self.command_wait_wall,
                'command':'把橙衣巡视员派到东侧 B1 复检位，把蓝衣巡视员派到 B2。长椅旁那位继续等，其他人照常。',
                'baseline':self.command_baseline},ensure_ascii=False,indent=2))
            e.event('cinematic_waiting_for_real_codex',frame=frame)
        if self.command_baseline and self.command_tasks is None:
            if abs(e.sim_time-self.command_sim_time)>1e-6:
                raise RuntimeError('simulation advanced during real-host wait; reject take')
            states=self.states()
            if all(states[aid]['control_epoch']>self.command_baseline[aid]['control_epoch'] and
                   states[aid]['task']['source']=='agent' for aid in HEROES):
                untouched=[aid for aid in states if aid not in HEROES]
                checks={aid:states[aid]['task_id']==self.command_baseline[aid]['task_id'] and
                        states[aid]['control_epoch']==self.command_baseline[aid]['control_epoch'] for aid in untouched}
                if not all(checks.values()):raise RuntimeError('a nonselected actor changed during the paused agent batch')
                self.command_tasks={aid:states[aid]['task_id'] for aid in HEROES}
                self.directory.joinpath('cinematic_agent_applied.json').write_text(json.dumps({
                    'frame':frame,'sim_time':e.sim_time,'wall_time':time.time(),'tasks':self.command_tasks,
                    'untouched_at_batch':checks,'wall_wait_s':time.time()-self.command_wait_wall,
                    'capture_policy':'simulation paused while real host thinks; no duplicated hold frames'},indent=2))
                e.cmd_resume({});e.backend.timeline.commit();e.event('cinematic_real_codex_batch_applied',tasks=self.command_tasks,frame=frame)
            elif time.time()-self.command_wait_wall>900:
                raise RuntimeError('real Codex command was not applied; preserve failed take')
        positions={aid:e.backend.observe(a['handle']).get('position_m',[0,0,0]) for aid,a in e.actors.items()}
        pose=self.camera.pose(frame,positions)
        camera=UsdGeom.Xformable(e.backend.stage.GetPrimAtPath('/World/Camera'))
        camera.GetOrderedXformOps()[0].Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(*pose['eye_m']),
            Gf.Vec3d(*pose['look_at_m']),Gf.Vec3d(0,0,1)).GetInverse())
        camera.GetPrim().GetAttribute('focalLength').Set(pose['focal_mm'])
        if e.backend.recorder:
            e.backend.recorder.focus_actor_id='seat_actor' if pose['shot']=='seat_cycle' else 'patrol_orange'
        self.needs_warmup = pose['shot'] != self.last_shot
        self.pose=pose

    def record(self, identity):
        if identity.get('video_frame') is None:return
        pose=self.pose
        state=self.states()
        boundary=self.last_shot is not None and pose['shot']!=self.last_shot
        cut=bool(boundary and self.previous_pose and
                 (sum((x-y)**2 for x,y in zip(pose['eye_m'],self.previous_pose['eye_m']))>.25 or
                  sum((x-y)**2 for x,y in zip(pose['look_at_m'],self.previous_pose['look_at_m']))>.25))
        self.log.write(json.dumps({**pose,'source_tick':round(identity['sim_time']*30),'journal_sample':identity['sample'],'sim_time':identity['sim_time'],
            'wall_time':time.time(),'video_frame':identity['video_frame'],'video_file':identity['video_file'],
            'camera_cut':cut,'shot_boundary':boundary,
            'actors':{aid:{'position_m':self.e.backend.observe(self.e.actors[aid]['handle'])['position_m'],
                           'task_id':state[aid]['task_id'],'control_epoch':state[aid]['control_epoch'],
                           'status':state[aid]['task']['status'],'step_index':state[aid]['task']['step_index'],
                           'step_phase':state[aid]['task']['step_phase']} for aid in self.e.actors}},ensure_ascii=False)+'\n')
        self.last_shot=pose['shot']
        self.previous_pose=pose
        if self.mode=='master' and identity['video_frame'] in {0,300,420,660,780,930,1020,1200,1320,1380,1530,1800,2040,2160,2400,2580}:
            from PIL import Image
            import numpy as np
            pixels=self.e.backend.recorder.rgb.get_data(device='cpu')
            folder=self.directory/'keyframes';folder.mkdir(exist_ok=True)
            Image.fromarray(np.ascontiguousarray(pixels[:,:,:3])).save(folder/f'frame_{identity["video_frame"]:05d}.png')

    def close(self):
        self.log.close()
        if self.mode=='technical':return
        final=self.states()
        result={'mode':self.mode,'source_frames':sum(1 for _ in (self.directory/'cinematic_frames.jsonl').open()),
                'agent_tasks':self.command_tasks,'hero_terminal':{aid:final[aid] for aid in HEROES},
                'waiter_task_unchanged':bool(self.command_baseline and final['bench_waiter']['task_id']==self.command_baseline['bench_waiter']['task_id']),
                'native_arrivals':{aid:bool(self.command_tasks and self.e.tasks[self.command_tasks[aid]]['status']=='succeeded') for aid in HEROES}}
        self.directory.joinpath('cinematic_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
