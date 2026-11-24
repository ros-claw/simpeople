"""Original procedural film sound, actual joint timing, local synthetic PA."""
import ast,ctypes as c,json,math,wave
from pathlib import Path
import numpy as np
from scipy.signal import butter,sosfilt,find_peaks,resample_poly
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'productions/platform04_feature90_review';FS=48000;DUR=90.;n=round(DUR*FS);t=np.arange(n)/FS;mix=np.zeros((n,2));rng=np.random.default_rng(9041126);events=[]
tree=ast.parse((ROOT/'.runtime/platform04/kit/audio/make_sound.py').read_text());defs=ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef)],type_ignores=[]);exec(compile(ast.fix_missing_locations(defs),'original_procedural_sound','exec'),globals())
rows=[json.loads(l) for l in (OUT/'evidence/actual_frames.jsonl').read_text().splitlines()];rig=json.loads((ROOT/'runs/platform04-motion-01/rig.json').read_text());leaf={name.rsplit('/',1)[-1]:i for i,name in enumerate(rig['joints'])}
bed=.004*np.sin(2*np.pi*53*t)+.003*np.sin(2*np.pi*108*t)+.004*nband(DUR,90,280)+.001*nband(DUR,850,2200);put(0,bed,1,-.08)
ids=sorted(set().union(*(set(r['actors']) for r in rows)))
for aid in ids:
    indices=[i for i,r in enumerate(rows) if aid in r['actors']];groups=[]
    for i in indices:
        if not groups or i>groups[-1][-1]+1:groups.append([i])
        else:groups[-1].append(i)
    for group in groups:
        for side in ['L','R']:
            z=np.array([rows[i]['actors'][aid]['actual_world_joints_m'][leaf[side+'_Foot']][2] for i in group]);peaks=find_peaks(-z,distance=5,prominence=.018)[0];selected={group[int(j)]:'actual ankle minimum timing proxy' for j in peaks}
            seen=set()
            for i in group:
                sup=rows[i]['actors'][aid].get('support',{}).get(side)
                if sup and sup.get('planted') and sup.get('support_is_full_weight') and sup['support_id'] not in seen:seen.add(sup['support_id']);selected[i]='authored support + actual shoe point'
            for i,origin in sorted(selected.items()):
                row=rows[i];actor=row['actors'][aid]
                if actor['speed_mps']<.15:continue
                camera=np.array(row['camera_matrix']);p=np.array(actor['root_world_m'])+[0,0,.1];local=(p-camera[3,:3])@camera[:3,:3].T;distance=np.linalg.norm(p-camera[3,:3]);pan=float(np.clip(local[0]/max(2,abs(local[2])*.65),-.85,.85));gain=(.22 if aid in ['H01','H02'] else .26 if aid in ['F01','F02','F03'] else .075)*min(1.2,np.sqrt(4/max(1.5,distance)))
                if actor.get('instance_pixels',1000)<50:gain*=.23
                inside=bool(aid=='F02' and p[1]<.15);start=i*1600;end=min(n,start+round(.245*FS));before=mix[start:end].copy();sole(i/30,gain,pan,0 if aid.startswith('H') else 1)
                if inside:delta=mix[start:end]-before;mix[start:end]=before+.72*sosfilt(butter(3,720,fs=FS,output='sos'),delta,axis=0)
                events.append({'time_s':i/30,'actor':aid,'side':side,'pan':pan,'source':origin,'inside_muffled':inside})
# The two strap sounds rhyme. No generic crowd scream loop covers the scene.
for at in [7.24,8.15,9.3,9.85,10.7,11.2,85.3,86.25,87.15,87.72,88.3]:texture(at,.13,380,2600,.10 if at<12 else .15,.18,.002,.035)
ring(22.30,.6,[(820,1),(1540,.5),(2780,.3)],.30,.35,.15)
for at,gain in [(22.49,.12),(22.74,.08),(23.10,.07)]:ring(at,.26,[(640,1),(1360,.36)],gain,.4,.09)
ring(26.2,.35,[(360,1),(920,.33)],.10,-.3,.09)
for at in [28.7,33.2,37.2,49.15,58.1,65.25,73.1]:
    texture(at,.50,90,480,.18,0,.002,.12);breath(at+.07,.38,.12,-.15,True)
texture(58.24,.35,500,3200,.16,-.2,.005,.12);texture(59.25,.44,300,2100,.20,.15,.006,.11)
for at in [60.0,60.5]:breath(at,.35,.13,-.12,True)
texture(65.2,.46,330,2600,.18,.35,.005,.12);ring(65.45,.25,[(210,1),(583,.33)],.12,.4,.08)
for at in [67.3,68.5,75.1,77.2,78.25,83.3,84.2]:breath(at,.55,.14,.08,False)
texture(79.08,1.18,400,2800,.12,0,.03,.65);ring(80.27,.45,[(220,1),(760,.55),(1410,.3)],.32,0,.12)
for at,gain in [(81.4,.43),(82.8,.24)]:
    texture(at,.32,100,1600,gain,-.2,.001,.09);ring(at,.5,[(165,1),(540,.6),(1080,.3)],gain*.8,-.2,.14)
# Original sparse pulse score; it starts only with the first attack and stops
# at the refuge. Its gain ducks under the committed miss.
env=np.clip((t-28)/7,0,1)*np.clip((83.1-t)/1.5,0,1);duck=1-.72*((t>57.8)&(t<61.5));score=(.012*np.sin(2*np.pi*41.2*t)+.008*np.sin(2*np.pi*58.27*t+.3*np.sin(t*.3)))*env*duck;put(0,score,1,0)
for at in np.arange(33.1,79.0,.73):
    gain=.028 if at<46 else .018 if at<64 else .043
    texture(float(at),.20,70,300,gain,-.12,.002,.055)
# Synthetic Mandarin PA, using the machine's installed eSpeak NG, not a clone
# or a transit operator's recording. API: official espeak-ng speak_lib.h.
lib=c.CDLL('libespeak-ng.so.1');lib.espeak_Initialize.argtypes=[c.c_int,c.c_int,c.c_char_p,c.c_int];rate=lib.espeak_Initialize(2,0,None,0);chunks=[];T=c.CFUNCTYPE(c.c_int,c.POINTER(c.c_short),c.c_int,c.c_void_p)
@T
def callback(w,count,ev):
    if w and count:chunks.append(np.ctypeslib.as_array(w,shape=(count,)).copy())
    return 0
lib.espeak_SetSynthCallback.argtypes=[T];lib.espeak_SetSynthCallback(callback);lib.espeak_SetVoiceByName.argtypes=[c.c_char_p];assert lib.espeak_SetVoiceByName(b'cmn')==0;lib.espeak_SetParameter(1,160,0);lib.espeak_SetParameter(3,56,0);lib.espeak_Synth.argtypes=[c.c_void_p,c.c_size_t,c.c_uint,c.c_int,c.c_uint,c.c_uint,c.c_void_p,c.c_void_p];message='请带好随身物品。'.encode();assert lib.espeak_Synth(message,len(message)+1,0,1,0,1,None,None)==0;lib.espeak_Synchronize();lib.espeak_Terminate();voice=np.concatenate(chunks).astype(float)/32768;voice=resample_poly(voice,320,147);voice=sosfilt(butter(3,[350,3300],fs=FS,btype='bandpass',output='sos'),voice);voice=.18*voice/max(1e-8,np.max(np.abs(voice)));put(87.1,voice,1,-.15)
ring(86.65,.28,[(664,1),(1328,.2)],.08,-.15,.12);ring(86.87,.3,[(887,1),(1774,.2)],.08,-.15,.13)
dry=mix.copy()
for delay,gain,flip in [(.029,.11,1),(.051,.08,0),(.079,.06,1),(.143,.025,0)]:
    k=round(delay*FS);mix[k:]+=gain*(dry[:-k,::-1] if flip else dry[:-k])
mix[:2400]*=np.linspace(0,1,2400)[:,None];mix[-12000:]*=np.linspace(1,0,12000)[:,None];mix=np.tanh(mix*1.5);mix*=10**(-1.5/20)/max(1e-8,np.max(np.abs(mix)))
path=OUT/'Original_Stereo_Soundtrack.wav'
with wave.open(str(path),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(FS);f.writeframes(np.round(mix*32767).astype('<i2').tobytes())
(OUT/'evidence/sound_events.json').write_text(json.dumps({'foot_events':events,'PA':{'time_s':87.1,'text':'请带好随身物品。','engine':'installed eSpeak NG cmn, original text, no cloned speaker','API_source':'https://github.com/espeak-ng/espeak-ng/blob/master/src/include/espeak-ng/speak_lib.h'},'scope':'original editorial synthesis; ankle minima are proxies, not microphones, acoustics or measured contact forces'},indent=2,ensure_ascii=False))
print('Original stereo soundtrack complete',len(events),'footfall timing proxies')
