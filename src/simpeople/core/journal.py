import csv
import json
from pathlib import Path
import statistics
import time

class Journal:
    def __init__(self,directory,config):
        self.directory=Path(directory); self.directory.mkdir(parents=True,exist_ok=True)
        self.events=(self.directory/'events.jsonl').open('a',buffering=1)
        self.trajectory=(self.directory/'trajectories.jsonl').open('a',buffering=1)
        self.performance=(self.directory/'performance.jsonl').open('a',buffering=1)
        self.write('config.json',config)
        self.start_wall=time.monotonic();self.frame_times=[];self.last_wall=self.start_wall
        self.first_sim=None; self.last_sim=0;self.frames=0
        self.warmup_s=config.get('warmup_wall_s',config.get('warmup_s',30 if config.get('scenario')=='industrial_life' else 0))
        self.measured_times=[];self.measured_start_sim=None;self.measured_start_wall=None
        self.timings={}

    def sample_timings(self,sample):
        if time.monotonic()-self.start_wall<self.warmup_s:return
        for key,value in sample.items():self.timings.setdefault(key,[]).append(value)
        if self.frames%30==0:self.performance.write(json.dumps({'kind':'timings',**sample})+'\n')

    def write(self,name,value):
        (self.directory/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

    def event(self,event):self.events.write(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n')

    def sample(self,engine,frame_identity=None):
        now=time.monotonic(); dt=now-self.last_wall; self.last_wall=now
        if self.first_sim is None:self.first_sim=engine.sim_time
        self.last_sim=engine.sim_time;self.frames+=1; self.frame_times.append(dt)
        if now-self.start_wall>=self.warmup_s:
            self.measured_times.append(dt)
            if self.measured_start_sim is None:self.measured_start_sim=engine.sim_time;self.measured_start_wall=now
        for aid,a in engine.actors.items():
            row={'actor_id':aid,'episode_id':engine.episode_id,'sim_time':engine.sim_time,
                 'task_id':a['task_id'],'control_epoch':a['control_epoch'],
                 **engine.backend.observe(a['handle'])}
            if frame_identity is not None:row['frame_identity']=frame_identity
            if getattr(engine.backend,'quality_sampling',False):
                task=engine.tasks.get(a['task_id'])
                if task:
                    row['task_step_index']=task['step_index'];row['task_step_phase']=task['step_phase']
                    row['requested_step']=task['steps'][task['step_index']] if task['step_index']<len(task['steps']) else None
                route=getattr(engine.backend,'routes',{}).get(getattr(engine.backend,'owner_routes',{}).get(a['handle']))
                if route:row['traffic']={k:route.get(k) for k in ('phase','status','segment_goal','native_task_id','retries','blocked_since')}
            self.trajectory.write(json.dumps(row,allow_nan=False)+'\n')
        if self.frames%30==0:
            self.performance.write(json.dumps({'sim_time':engine.sim_time,'wall_elapsed_s':now-self.start_wall,
                'frame_time_s':dt,'phase':'warmup' if now-self.start_wall<self.warmup_s else 'measurement',
                'actors':len(engine.actors)})+'\n')

    def finish(self,engine,**extra):
        wall=getattr(self,'measurement_end_wall',time.monotonic())-self.start_wall
        times=sorted(self.measured_times or self.frame_times)
        measured_wall=getattr(self,'measurement_end_wall',time.monotonic())-(self.measured_start_wall or self.start_wall)
        measured_sim=self.last_sim-(self.measured_start_sim or self.first_sim or 0)
        statuses={s:sum(t['status']==s for t in engine.tasks.values()) for s in
                  ['accepted','running','paused','blocked','succeeded','failed','cancelled']}
        metrics={'sim_elapsed_s':self.last_sim-(self.first_sim or 0),'wall_elapsed_s':wall,
                 'rtf':measured_sim/measured_wall,'overall_rtf':(self.last_sim-(self.first_sim or 0))/wall,
                 'warmup_target_wall_s':self.warmup_s,'measurement_wall_s':measured_wall,
                 'measurement_sim_s':measured_sim,'rendered_updates':self.frames,
                 'updates_per_wall_second':self.frames/wall,
                 'measured_updates_per_wall_second':len(self.measured_times)/measured_wall,
                 'frame_time_median_s':statistics.median(times) if times else None,
                 'frame_time_p95_s':times[min(len(times)-1,int(.95*len(times)))] if times else None,
                 'task_status_counts':statuses,
                 'actors':{aid:{'completed_activities':a['cycles']} for aid,a in engine.actors.items()},**extra}
        if engine.population:metrics['population']=engine.population.assignments
        metrics['stage_time_medians_s']={k:statistics.median(v) for k,v in self.timings.items() if v}
        self.write('metrics.json',metrics);self.write('tasks.json',[engine.public(t) for t in engine.tasks.values()])
        for f in [self.events,self.trajectory,self.performance]:f.close()
        return metrics
