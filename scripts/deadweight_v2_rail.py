"""Counterfactual mechanics and actual USD wheel readbacks in Isaac 6.2.

One DOF solver + kinematic wheel rendering. No PhysX contact claim.
"""
import argparse,os,sys,json,shutil,importlib.util,math,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=3);p.add_argument('--no-clips',action='store_true');args=p.parse_args();out=ROOT/'runs'/args.run_id;out.mkdir(parents=True,exist_ok=False)
(out/'bootstrap.json').write_text(json.dumps({'pid':os.getpid(),**vars(args)}))
for file in [Path(__file__),ROOT/'src/simpeople/core/funicular.py',*list((ROOT/'src/simpeople/backends/native').glob('deadweight*.py')),ROOT/'.runtime/deadweight_v2/repair_kit/tools/rail_audit.py']:
 dest=out/'source_snapshot'/file.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,dest)
shutil.copytree(ROOT/'src/simpeople',out/'source_snapshot/src/simpeople',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
(out/'input_hashes.json').write_text(json.dumps({str(f.relative_to(out/'source_snapshot')):hashlib.sha256(f.read_bytes()).hexdigest() for f in (out/'source_snapshot').rglob('*') if f.is_file()},indent=2))
sys.path.insert(0,str(out/'source_snapshot/src'))
sys.argv=[sys.argv[0]]
from isaacsim import SimulationApp
app=SimulationApp({'headless':True,'active_gpu':args.gpu,'multi_gpu':False,'limit_cpu_threads':8,'disable_viewport_updates':True});rec=None;code=0
try:
 import omni.usd,omni.timeline,numpy as np
 from dataclasses import replace
 from pxr import Gf,UsdGeom
 from simpeople.core.funicular import Funicular,FunicularParameters
 from simpeople.backends.native.deadweight_v2_set import create_scene,aim,T,N
 from simpeople.backends.native.recording import Recorder
 spec=importlib.util.spec_from_file_location('rail_audit',ROOT/'.runtime/deadweight_v2/repair_kit/tools/rail_audit.py');audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
 omni.usd.get_context().new_stage();stage=omni.usd.get_context().get_stage();cars,geom=create_scene(stage,ROOT);timeline=omni.timeline.get_timeline_interface();timeline.set_auto_update(False);timeline.play();timeline.commit()
 report={'model':'one degree of freedom ideal cable dynamics + Isaac 6.2 rendering','not_measured':['PhysX wheel contacts','contact impulses','cable elasticity','independent real vehicle validation'],'cases':{}};series={}
 cases=[('equal',4000,4000,0,0,120,8),('loaded',4800,4000,0,0,120,8),('extra_74kg',4874,4000,0,0,120,8),('swapped',4000,4800,0,0,120,8),('door_hold',4800,4000,0,0,120,8),('authorization_hold',4800,4000,0,0,120,8),('door_fault_in_motion',4800,4000,0,0,120,8),('brake_11200',4800,4000,3,11200,120,6),('brake_8400',4800,4000,3,8400,120,8),('brake_dt60',4800,4000,3,11200,60,6)]
 for name,ma,mb,v,brake,hz,duration in cases:
  par=FunicularParameters(empty_A_kg=ma,empty_B_kg=mb,water_B_kg=0,speed_limit_mps=10,brake_max_N=brake or 11200);c=Funicular(par,q=56,v=v,auto_dock=False);c.authorized=name!='authorization_hold';c.doors_closed=name!='door_hold'
  if name not in ['door_hold','authorization_hold']:assert c.release()
  else:assert not c.release()
  if brake:c.fault_door_contact()
  geom.previous_angles={};rows=[];samples=[]
  for i in range(int(duration*hz)+1):
   if name=='door_fault_in_motion' and i==360:
    before=c.v;c.fault_door_contact();report['door_fault_event']={'before_speed_mps':before,'after_contact_change_speed_mps':c.v,'fault_q_m':c.q,'solver_time_s':c.t};assert before==c.v and before>0
   if i:c.step(1/hz)
   geom.apply(c.q);sample=c.sample();samples.append(sample);rows.append({'frame':i,'t_s':i/hz,'phase':'candidate','nongravity_signed_q_N':sample['nongravity_signed_q_N'],**geom.read()})
  # Centered finite-difference force audit only inside an unchanged force mode.
  for i,row in enumerate(rows):
   lo=max(0,i-2);hi=min(len(rows),i+3);row['phase']='rolling' if len(set(s['mode'] for s in samples[lo:hi]))==1 and samples[i]['mode'] not in ['parked','static','stopped'] else 'transition_or_static'
  cfg=geom.calibration();cfg['min_observed_travel_m']=.1;cfg['mechanics']={'mass_A_kg':ma,'mass_B_kg':mb,'reflected_rotating_mass_kg':160};cfg['limits']['force_N']=2.
  folder=out/name;folder.mkdir();(folder/'calibration.json').write_text(json.dumps(cfg,indent=2));(folder/'wheel_readbacks.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows));(folder/'solver.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in samples))
  delta=c.q-56;qa=audit.audit(cfg,rows) if abs(delta)>.1 else {'passed':None,'scope':'stationary: rolling audit correctly not applicable'}
  initial_a=next((s['a_mps2'] for s in samples[1:] if abs(s['v_mps'])>1e-8),0.)
  report['cases'][name]={'mass_A_kg':ma,'mass_B_kg':mb,'initial_acceleration_mps2':initial_a,'travel_m':delta,'last_speed_mps':c.v,'max_energy_residual_J':max(abs(s['energy_residual_J']) for s in samples),'wheel_audit':qa};series[name]=samples
  print('case',name,delta,qa['passed'],flush=True)
 # Production trip uses the same ledger IDs as the 36 rendered people.
 c=Funicular();kw=dict(inside=True,feet_supported=True,stable_s=.5,speed_mps=0)
 for i in range(23):c.add_passenger(f'infected_{i+1:02d}','A',74,**kw)
 c.add_passenger('heroine','A',76,**kw)
 for i in range(12):c.add_passenger(f'survivor_{i+1:02d}','B',75,**kw)
 c.doors_closed=c.authorized=True;assert c.release();production=[c.sample()];geom.previous_angles={};triprows=[]
 for i in range(20000):
  geom.apply(c.q);triprows.append({'frame':i,'t_s':i/120,**geom.read()})
  if c.locked and i:break
  c.step(1/120);production.append(c.sample())
 (out/'production_profile.json').write_text(json.dumps(production));(out/'production_wheel_readbacks.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in triprows));cfg=geom.calibration();tripqa=audit.audit(cfg,triprows)
 meeting=min(production,key=lambda s:abs(s['q_m']-56));report['production']={'masses_kg':c.masses,'ledger':c.passengers,'travel_time_s':c.t,'arrival_q_m':c.q,'meeting_time_s':meeting['solver_time_s'],'meeting_q_m':meeting['q_m'],'max_energy_residual_J':max(abs(s['energy_residual_J']) for s in production),'wheel_audit':tripqa}
 a=report['cases'];report['checks']={'equal_stays_still':abs(a['equal']['travel_m'])<1e-10,'swapping_reverses':abs(a['loaded']['travel_m']+a['swapped']['travel_m'])<1e-8,'extra_mass_faster':a['extra_74kg']['initial_acceleration_mps2']>a['loaded']['initial_acceleration_mps2'],'door_holds':a['door_hold']['travel_m']==0,'authorization_holds':a['authorization_hold']['travel_m']==0,'moving_door_fault_stops_after_finite_distance':a['door_fault_in_motion']['last_speed_mps']==0 and a['door_fault_in_motion']['travel_m']+56>report['door_fault_event']['fault_q_m'],'weaker_brake_longer_stop':a['brake_8400']['travel_m']>a['brake_11200']['travel_m'],'dt60_120_stop_difference_below_1mm':abs(a['brake_dt60']['travel_m']-a['brake_11200']['travel_m'])<.001,'all_moving_wheel_audits':all(x['wheel_audit']['passed'] for x in a.values() if x['wheel_audit']['passed'] is not None),'production_wheels':tripqa['passed']}
 (out/'physics_regression.json').write_text(json.dumps(report,indent=2));assert all(report['checks'].values()),report['checks']
 # Fixed world camera. Equal/loaded share exactly the same pose and initial q.
 geom.apply(56);wheel=np.array(geom.read()['A']['wheels']['0_0']['center_world_m']);target=wheel-T*1.1;eye=target+np.array([-2,-5,1.7]);aim(stage,eye,target,35);rec=Recorder(out,(1920,1080),gpu_index=args.gpu)
 clips=[]
 for name,duration in ([] if args.no_clips else [('equal',4),('loaded',6),('brake_11200',6),('brake_8400',8)]):
  samples=series[name];geom.apply(samples[0]['q_m'])
  for _ in range(8):rec.step(0)
  index=len(clips);rec.control({'mode':'start'})
  for f in range(duration*30):
   s=samples[min(len(samples)-1,f*4)];geom.apply(s['q_m']);rec.step(1/30);rec.step(0);rec.capture(timeline.get_current_time(),{'case':name,'source_tick':f,'solver_time_s':s['solver_time_s'],'q_m':s['q_m'],'camera_fixed':True})
  info=rec.close();clips.append({'case':name,**info});print('clip',name,flush=True)
 (out/'clips.json').write_text(json.dumps(clips,indent=2));stage.GetRootLayer().Export(str(out/'scene.usda'));(out/'completed.json').write_text(json.dumps({'checks':report['checks'],'clips':clips},indent=2))
except Exception:
 import traceback;traceback.print_exc();(out/'failed.txt').write_text(traceback.format_exc());code=1
finally:
 if rec:rec.close()
 app.close()
raise SystemExit(code)
