"""Original stereo editorial Foley; ankle minima are timing proxies, not force."""
import ast,json,wave
from pathlib import Path
import numpy as np
from scipy.signal import find_peaks,butter,sosfilt
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/platform04_directors_review';FS=48000;DUR=10.;rng=np.random.default_rng(9042026);n=round(DUR*FS);t=np.arange(n)/FS;mix=np.zeros((n,2))
tree=ast.parse((ROOT/'.runtime/platform04/kit/audio/make_sound.py').read_text());defs=ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef)],type_ignores=[]);exec(compile(ast.fix_missing_locations(defs),'original_kit_foley_functions','exec'),globals())
rows=[json.loads(l) for l in (OUT/'evidence/04_Door_Uncut_10s/frames.jsonl').read_text().splitlines()];names=json.loads((ROOT/'runs/platform04-motion-01/rig.json').read_text())['joints'];leaf={n.rsplit('/',1)[-1]:i for i,n in enumerate(names)};events=[]
bed=.005*np.sin(2*np.pi*53*t)+.003*np.sin(2*np.pi*108*t)+.006*nband(DUR,90,280)+.001*nband(DUR,800,2200);put(0,bed,1,-.08)
for aid in rows[0]['actors']:
 if aid in ['H02','H03','F03']:continue
 for side in ['L','R']:
  z=np.array([r['actors'][aid]['actual_world_joints_m'][leaf[side+'_Foot']][2] for r in rows]);peaks=find_peaks(-z,distance=5,prominence=.018)[0]
  for f in peaks:
   row=rows[f];a=row['actors'][aid]
   if a['speed_mps']<.7:continue
   camera=np.asarray(row['camera_matrix']);p=np.array(a['root_world_m'])+[0,0,.1];local=(p-camera[3,:3])@camera[:3,:3].T;pan=float(np.clip(local[0]/max(2,abs(local[2])*.6),-.85,.85));distance=float(np.linalg.norm(p-camera[3,:3]));gain=(.33 if aid=='H01' else .34 if aid in ['F01','F02'] else .055)*min(1.2,np.sqrt(5/max(1.5,distance)));at=f/30;inside=aid=='F02' and a['root_world_m'][1]<.35;start=mix.copy() if inside else None;sole(at,gain,pan,0 if aid=='H01' else 1)
   if inside:
    event=mix-start;filtered=sosfilt(butter(3,750,fs=FS,output='sos'),event,axis=0);mix[:]=start+filtered*.8
   events.append({'output_frame':int(f),'time_s':at,'actor_id':aid,'side':side,'pan':pan,'inside_muffled':inside,'source':'actual world ankle-height minimum with prominence >=18mm; editorial footfall timing proxy, not contact force'})
texture(6.27,.24,500,3300,.11,-.05,.01,.08);breath(6.42,.31,.11,.05);breath(8.8,.5,.10,.13,False)
dry=mix.copy()
for delay,gain,flip in [(.028,.12,1),(.047,.10,0),(.074,.075,1),(.131,.04,0),(.243,.02,1)]:
 k=round(delay*FS);mix[k:]+=gain*(dry[:-k,::-1] if flip else dry[:-k])
mix[:2400]*=np.linspace(0,1,2400)[:,None];mix[-4800:]*=np.linspace(1,0,4800)[:,None];mix*=10**(-2/20)/max(1e-8,np.max(np.abs(mix)))
with wave.open(str(OUT/'Door_OriginalFoley.wav'),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(FS);f.writeframes(np.round(mix*32767).astype('<i2').tobytes())
(OUT/'Door_OriginalFoley.events.json').write_text(json.dumps({'events':events,'scope':'original synthesized editorial sound and stereo panning from actual camera/positions; no recorded microphone, acoustic or physical contact simulation'},indent=2))
print('original Foley foot events',len(events))
