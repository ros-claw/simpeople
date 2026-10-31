"""Compare observed standing Idle frames; deliberate queue waits also count."""
import argparse,json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def measure(run_id):
    d=ROOT/'runs'/run_id;total=Counter();idle=Counter();native=Counter();excluded={'patrol_orange','patrol_blue','bench_waiter'}
    for line in (d/'trajectories.jsonl').open():
        r=json.loads(line)
        if r.get('frame_identity',{}).get('video_frame') is None or r['actor_id'] in excluded:continue
        aid=r['actor_id'];total[aid]+=1;native[r.get('action') or 'none']+=1
        if r.get('action')=='Idle' and r.get('planar_speed_mps',0)<.15:idle[aid]+=1
    return {'run_id':run_id,'eligible_actors':len(total),'standing_idle_fraction':sum(idle.values())/sum(total.values()),
            'per_actor':{aid:idle[aid]/count for aid,count in total.items()},'native_action_frame_counts':dict(native)}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    result={'definition':'Native Idle and planar root speed <0.15 m/s. Excludes two story heroes and the intentional witness in both runs. Includes legitimate queue and traffic waits; not a diagnosis of boredom or foot slipping.',
            'before':measure(a.before),'after':measure(a.after)}
    result['percentage_point_change']=(result['after']['standing_idle_fraction']-result['before']['standing_idle_fraction'])*100
    Path(a.output).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['percentage_point_change']},ensure_ascii=False))
