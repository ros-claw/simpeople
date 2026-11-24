"""Assemble the reviewed repair take without retiming any action frames."""
import json,subprocess,shutil,hashlib,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from check_master import check
OUT=ROOT/'productions/deadweight_v2_review';OUT.mkdir(exist_ok=True)
base=ROOT/'runs/deadweight-v2-trial-01';patch=ROOT/'runs/deadweight-v2-wheel-retake-03';escape=ROOT/'runs/deadweight-v2-escape-retake-01'
for folder in [base,patch,escape]:
 if not (folder/'completed.json').exists() or (folder/'failed.txt').exists():raise RuntimeError('unclosed/failed source: '+str(folder))
rows={r['source_tick']:r for r in map(json.loads,(base/'frames.jsonl').read_text().splitlines())};retake={r['source_tick']:r for r in map(json.loads,(patch/'frames.jsonl').read_text().splitlines())}
ending={r['source_tick']:r for r in map(json.loads,(escape/'frames.jsonl').read_text().splitlines())};assert len(rows)==720 and len(retake)==120 and len(ending)==135
qerror=max(abs(rows[f]['solver_state']['q_m']-r['solver_state']['q_m']) for f,r in retake.items());assert qerror<1e-9,qerror
dest=OUT/'DEADWEIGHT_V2_24s_1080p30_Clean.mp4'
subprocess.run(['ffmpeg','-v','error','-y','-i',str(base/'raw_video.mp4'),'-i',str(patch/'raw_video.mp4'),'-i',str(escape/'raw_video.mp4'),'-filter_complex','[0:v]trim=start_frame=0:end_frame=315,setpts=PTS-STARTPTS[a];[1:v]trim=start_frame=0:end_frame=120,setpts=PTS-STARTPTS[b];[0:v]trim=start_frame=435:end_frame=585,setpts=PTS-STARTPTS[c];[2:v]trim=start_frame=0:end_frame=135,setpts=PTS-STARTPTS[d];[a][b][c][d]concat=n=4:v=1:a=0[out]','-map','[out]','-an','-fps_mode','passthrough','-c:v','libx264','-preset','slow','-crf','18','-threads','4','-pix_fmt','yuv420p','-movflags','+faststart',str(dest)],check=True)
validation=check(dest,frames=720);clockfix=None
if validation['errors']==['incorrect duration']:
 def packet_hashes(file):
  result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_packets','-show_data_hash','sha256','-show_entries','packet=data_hash','-of','json',str(file)],capture_output=True,text=True,check=True)
  return [p['data_hash'] for p in json.loads(result.stdout)['packets']]
 fixed=dest.with_name(dest.stem+'_clockfix.mp4')
 subprocess.run(['ffmpeg','-v','error','-y','-i',str(dest),'-map','0','-c','copy','-bsf:v','setts=pts=PTS:dts=DTS:duration=1/(30*TB)','-video_track_timescale','30000','-movflags','+faststart',str(fixed)],check=True)
 assert packet_hashes(dest)==packet_hashes(fixed),'compressed packets changed'
 clockfix={'old_duration_s':validation['stream']['duration'],'compressed_packets_unchanged':True,'PTS_DTS_explicitly_retained':True,'reason':'concat last packet duration was zero'}
 shutil.move(dest,ROOT/f'.runtime/deadweight_v2/master_before_clock_fix_{time.time_ns()}.mp4');fixed.rename(dest);validation=check(dest,frames=720)
assert validation['passed'],validation
for label,filename in [('Equal_4s','raw_video.mp4'),('Loaded_6s','raw_video_001.mp4'),('Brake_11kN_6s','raw_video_002.mp4'),('Brake_8kN_8s','raw_video_003.mp4')]:shutil.copy2(ROOT/'runs/deadweight-v2-rail-01'/filename,OUT/(label+'.mp4'))
shutil.copy2(ROOT/'runs/deadweight-v2-wardrobe-03/raw_video.mp4',OUT/'Heroine_FourActions_9s.mp4')
for f in [0,89,139,190,290,330,400,510,645,710]:shutil.copy2((escape if f in ending else patch if f in retake else base)/f'frame_{f:04d}.png',OUT/f'frame_{f:04d}.png')
shutil.copy2(base/'frame_0510.png',OUT/'Meeting_Physics_Midpoint.png')
for name in ['none','single','double']:shutil.copy2(base/f'glass_{name}.png',OUT/f'glass_{name}.png')
for file in (ROOT/'runs/deadweight-v2-scene-03').glob('*.png'):shutil.copy2(file,OUT/file.name)
for name in ['eleven_costumes','hands_down','hand_raised','wrist_turn','window_gesture']:shutil.copy2(ROOT/'runs/deadweight-v2-wardrobe-03'/(name+'.png'),OUT/(name+'.png'))
for name,source in [('physics_regression.json',ROOT/'runs/deadweight-v2-rail-02/physics_regression.json'),('deformed_shoe_qa.json',base/'deformed_shoe_qa.json'),('rgb_pose_alignment.json',base/'rgb_pose_alignment.json'),('mitt_window_clearance.json',ROOT/'runs/deadweight-v2-wardrobe-03/mitt_window_clearance.json')]:shutil.copy2(source,OUT/name)
edl=[];unified=[]
for f in range(720):
 run=escape if f in ending else patch if f in retake else base;r=dict(ending[f] if f in ending else retake[f] if f in retake else rows[f]);r['source_run_id']=run.name;r['output_frame']=f;r['output_pts_s']=f/30;r['rail_angle_scope']='locally unwrapped actual mesh phase; cumulative revolutions across travel edits require full production wheel trace';unified.append(r)
 if not edl or edl[-1]['source_run_id']!=run.name:edl.append({'source_run_id':run.name,'output_first_frame':f,'source_first_tick':f,'output_last_frame':f})
 else:edl[-1]['output_last_frame']=f
(OUT/'master_frame_map.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in unified))
duplicates=sum(a['rgb_sha256']==b['rgb_sha256'] for a,b in zip(unified,unified[1:]));assert duplicates==0
manifest={'movie':dest.name,'validation':validation,'packet_duration_normalization':clockfix,'original_speed':True,'fps':30,'frames':720,'duration_s':24,'edit_decisions':edl,'retake_max_same_tick_q_difference_m':qerror,'source_rgb_adjacent_full_duplicates':duplicates,'no_motion_interpolation':True,'source_clock':'each output action frame advances its source state by 1/30 s; hard cuts omit elapsed travel at 14.5 and 19.5 seconds','scope':'repair rehearsal; 1D dynamics + Isaac rendering; full pose cache actors; no PhysX contacts/Native ride claim','verified_tests':104,'human_mute_review':{'status':'not_measured','questions':['什么让车开起来？','两人交会时想做什么？','女主最后去了哪里？']},'remaining':['coast material repetition and terrain detailing','readability of the hand gag without captions','full-body collision and PhysX wheel contacts not measured'],'failed_take':'deadweight-v2-wheel-retake-01 black shot rejected; not used'}
(OUT/'DELIVERY.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False));print(json.dumps(manifest,ensure_ascii=False,indent=2))
