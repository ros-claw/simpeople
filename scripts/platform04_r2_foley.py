"""Optional editorial sound. Blind media remain untouched and silent."""
import ast,json,wave,math
from pathlib import Path
import numpy as np
from scipy.signal import find_peaks,butter,sosfilt
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/platform04_r2_review';FS=48000;DUR=10.;rng=np.random.default_rng(420261103);n=round(DUR*FS);t=np.arange(n)/FS;mix=np.zeros((n,2));events=[]
tree=ast.parse((ROOT/'.runtime/platform04/kit/audio/make_sound.py').read_text());defs=ast.Module(body=[v for v in tree.body if isinstance(v,ast.FunctionDef)],type_ignores=[]);exec(compile(ast.fix_missing_locations(defs),'original_procedural_foley','exec'),globals())
rows=[json.loads(l) for l in (ROOT/'runs/platform04-r2-trio-06/frames.jsonl').read_text().splitlines()];names=json.loads((ROOT/'runs/platform04-motion-01/rig.json').read_text())['joints'];leaf={n.rsplit('/',1)[-1]:i for i,n in enumerate(names)}
bed=.004*np.sin(2*np.pi*53*t)+.003*np.sin(2*np.pi*108*t)+.005*nband(DUR,90,280)+.001*nband(DUR,900,2400);put(0,bed,1,-.08)
for aid in rows[0]['actors']:
 selected=[]
 for side in ['L','R']:
  seen=set()
  for f,r in enumerate(rows):
   s=r['actors'][aid].get('support',{}).get(side)
   if s and s['planted'] and s['support_is_full_weight'] and s['support_id'] not in seen:seen.add(s['support_id']);selected.append((f,side,'authored support window + actual skinned sole'))
  z=np.array([r['actors'][aid]['actual_world_joints_m'][leaf[side+'_Foot']][2] for r in rows]);peaks=find_peaks(-z,distance=5,prominence=.018)[0]
  for f in peaks:
   if rows[f]['actors'][aid].get('foot_phrase_weight',0)>.5:continue
   selected.append((int(f),side,'actual ankle minimum proxy outside authored support phrase'))
 for f,side,source in sorted(selected):
  row=rows[f];a=row['actors'][aid]
  if a['speed_mps']<.15:continue
  p=np.array(a['root_world_m'])+[0,0,.1];camera=np.array(row['camera_matrix']);local=(p-camera[3,:3])@camera[:3,:3].T;pan=float(np.clip(local[0]/max(2,abs(local[2])*.6),-.85,.85));distance=float(np.linalg.norm(p-camera[3,:3]));gain=(.29 if aid=='H01' else .38 if aid=='F02' else .07)*min(1.2,np.sqrt(5/max(1.5,distance)));inside=aid=='F02' and a['root_world_m'][1]<.15;before=mix.copy() if inside else None;sole(f/30,gain,pan,0 if aid=='H01' else 1)
  if inside:
   event=mix-before;mix[:]=before+.75*sosfilt(butter(3,720,fs=FS,output='sos'),event,axis=0)
  events.append({'f':f,'actor':aid,'side':side,'source':source,'pan':pan,'inside_muffled':inside})
texture(4.68,.28,500,3100,.07,-.15,.01,.1);texture(5.22,.38,300,3900,.16,-.1,.005,.09);breath(5.2,.28,.10,-.15,True);breath(6.2,.36,.12,-.10,True);breath(6.8,.35,.11,.2,False)
dry=mix.copy()
for delay,gain,flip in [(.029,.12,1),(.049,.09,0),(.078,.06,1),(.139,.035,0)]:
 k=round(delay*FS);mix[k:]+=gain*(dry[:-k,::-1] if flip else dry[:-k])
mix[:2400]*=np.linspace(0,1,2400)[:,None];mix[-4800:]*=np.linspace(1,0,4800)[:,None];mix*=10**(-2/20)/max(1e-8,np.max(np.abs(mix)));path=OUT/'D03_Original_Foley.wav'
with wave.open(str(path),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(FS);f.writeframes(np.round(mix*32767).astype('<i2').tobytes())
(OUT/'D03_Original_Foley.events.json').write_text(json.dumps({'events':events,'scope':'original procedural editorial sound, not microphone capture, acoustic simulation or measured contact force; not included in blind trials'},indent=2))
