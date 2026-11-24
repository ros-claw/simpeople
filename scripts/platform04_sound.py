"""Original event-based stereo Foley from the actual movie's gait phases.

Editorial synthesis and panning, not microphone capture or acoustic physics.
Source functions originate in the user-supplied production kit.
"""
import argparse,ast,json,math,wave
from pathlib import Path
import numpy as np
from scipy.signal import butter,sosfilt
ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();p.add_argument('--run-id',default='platform04-master-01');p.add_argument('--out',type=Path,required=True);args=p.parse_args();source=ROOT/'runs'/args.run_id;rows=[json.loads(l) for l in (source/'frames.jsonl').open()];fits=json.loads((source/'actor_fits.json').read_text());FS=48000;DUR=18.;rng=np.random.default_rng(40112026);n=round(DUR*FS);t=np.arange(n)/FS;mix=np.zeros((n,2))
# Load only the original procedural Foley definitions; do not execute its
# prewritten timings, default output, or original mix.
tree=ast.parse((ROOT/'.runtime/platform04/kit/audio/make_sound.py').read_text());defs=ast.Module(body=[x for x in tree.body if isinstance(x,ast.FunctionDef)],type_ignores=[]);exec(compile(ast.fix_missing_locations(defs),'kit_original_foley_functions','exec'),globals())
events=[]
def location(row,aid):
    camera=np.asarray(row['camera_matrix']);p=np.asarray(row['actors'][aid]['root_world_m'])+np.array([0,0,.10]);local=(p-camera[3,:3])@camera[:3,:3].T;pan=float(np.clip(local[0]/max(2,abs(local[2])*.6),-.88,.88));distance=float(np.linalg.norm(p-camera[3,:3]));return pan,distance

bed=.007*np.sin(2*np.pi*53*t)+.005*np.sin(2*np.pi*108*t+.08*np.sin(t*.3))+.008*nband(DUR,90,280)+.002*nband(DUR,800,2200);put(0,bed,1,-.08)
# A quiet phone drop and hand twitch before the burst. Silence carries it.
ring(1.67,.28,[(1650,1),(2490,.35)],.13,-.25,.09);texture(1.67,.12,500,4600,.12,-.25,.001,.026);texture(1.56,.23,900,4700,.10,-.3,.006,.06);breath(2.73,.32,.12,-.45)
previous={aid:None for aid in rows[0]['actors']};last_hit={aid:-10. for aid in previous}
for row in rows:
    at=row['movie_time_s']
    for aid,r in row['actors'].items():
        clip=r['gait'];f=fits[aid][clip];phase=int(r['phase'])%f['period'];side=f['support'][phase];fresh=side is not None and side!=previous[aid];previous[aid]=side
        if not fresh or r['speed_mps']<.55 or r['motion_weight']<.25 or at-last_hit[aid]<.17:continue
        last_hit[aid]=at;pan,distance=location(row,aid);foreground=aid in ['hero','chaser','intercept'];gain=(.35 if aid=='hero' else .40 if aid=='chaser' else .37 if aid=='intercept' else .075)*min(1.25,math.sqrt(5/max(1.5,distance)))
        start=mix.copy() if aid=='intercept' else None
        sole(at,gain,pan,0 if aid in ['hero','witness','bystander'] else 1)
        inside=aid=='intercept' and r['root_world_m'][1]<.35
        if inside:
            # The same foot events lose high frequencies behind the pane.
            event=mix-start;filtered=sosfilt(butter(3,750,fs=FS,output='sos'),event,axis=0);openness=float(np.clip((r['root_world_m'][1]+.3)/.65,0,1));mix[:]=start+(event*openness+filtered*(1-openness))*.80
        events.append({'time_s':at,'actor_id':aid,'side':side,'phase':r['phase'],'pan':pan,'gain':gain,'inside_muffled':inside,'source':'fitted actual shoe support phase + recorded actual movie position'})
# Brief scrape and uncontrolled recovery; avoid continuous monster roars.
texture(11.28,.34,550,3800,.19,.08,.01,.13);texture(12.08,.40,160,2200,.27,-.04,.003,.09);sole(12.35,.32,-.05,1);sole(12.68,.20,.13,1)
breath(11.55,.33,.16,.02);breath(13.38,.44,.14,.1,False);breath(13.95,.62,.18,.08,True);breath(15.50,.45,.12,.05,False);breath(16.1,.57,.16,.1,True)
texture(13.40,.32,500,2600,.10,.65,.008,.09) # low attacker presses the bench edge
ring(16.72,.5,[(367,1),(752,.6),(1633,.24)],.30,.14,.13);texture(16.73,.22,240,3200,.20,.14,.001,.04)
ring(17.16,.40,[(664,1),(1328,.20)],.07,-.05,.16);ring(17.52,.46,[(887,1),(1774,.20)],.07,-.05,.20)
dry=mix.copy()
for delay,gain,flip in [(.028,.12,1),(.047,.10,0),(.074,.075,1),(.131,.04,0),(.243,.02,1)]:
    k=round(delay*FS);mix[k:]+=gain*(dry[:-k,::-1] if flip else dry[:-k])
mix[:2400]*=np.linspace(0,1,2400)[:,None];mix[-4800:]*=np.linspace(1,0,4800)[:,None];mix*=10**(-2/20)/max(1e-8,np.max(np.abs(mix)));args.out.parent.mkdir(parents=True,exist_ok=True)
with wave.open(str(args.out),'wb') as f:f.setnchannels(2);f.setsampwidth(2);f.setframerate(FS);f.writeframes(np.round(mix*32767).astype('<i2').tobytes())
args.out.with_suffix('.events.json').write_text(json.dumps({'scope':'original synthesized editorial Foley; foot phases measured from fitted geometry, spatialization from recorded positions; not contact-force or acoustic simulation','events':events},indent=2));print(args.out,len(events),'foot events')
