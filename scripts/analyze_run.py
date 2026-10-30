"""Derive validation measurements from runtime trajectories, never from task names alone."""
import argparse
import json
import math
from pathlib import Path
import statistics

def analyze(directory):
    directory=Path(directory)
    events=[json.loads(x) for x in (directory/'events.jsonl').read_text().splitlines()]
    rows=[json.loads(x) for x in (directory/'trajectories.jsonl').read_text().splitlines()]
    by_actor={}
    for row in rows:
        if not row['ready']:continue
        aid=row['actor_id'];previous=by_actor.get(aid)
        row['measured_speed_mps']=0
        if previous and row['sim_time']>previous['sim_time']:
            row['measured_speed_mps']=math.dist(row['position_m'],previous['position_m'])/(row['sim_time']-previous['sim_time'])
        by_actor[aid]=row
    steps=[]
    for event in events:
        if event['kind']!='step_started':continue
        ended=next((e for e in events if e['kind']=='step_ended' and e['task_id']==event['task_id'] and e['index']==event['index']),None)
        if not ended:continue
        segment=[r for r in rows if r['actor_id']==event['actor_id'] and event['sim_time']<=r['sim_time']<=ended['sim_time'] and r['ready']]
        if not segment:continue
        step={'index':event['index'],'actor_id':event['actor_id'],'step':event['step'],
              'start_sim_time':event['sim_time'],'end_sim_time':ended['sim_time'],
              'final_position_m':segment[-1]['position_m'],'final_measured_speed_mps':segment[-1]['measured_speed_mps']}
        moving=[r for r in segment if event['sim_time']+1<r['sim_time']<ended['sim_time']-1 and r['measured_speed_mps']>.5]
        if moving:
            speeds=[r['measured_speed_mps'] for r in moving]
            step.update(cruise_speed_median_mps=statistics.median(speeds),max_speed_mps=max(speeds))
        # Toe joint proxies; do not interpret this geometric proxy as contact-force sensing.
        slips=[]
        for tag in ['LeftToeBase','RightToeBase']:
            contact=[]
            for prev,row in zip(segment,segment[1:]):
                a=prev.get('joints_m',{}).get(tag);b=row.get('joints_m',{}).get(tag)
                dt=row['sim_time']-prev['sim_time']
                low=b and a and dt>0 and b[2]<.07 and abs(b[2]-a[2])/dt<.1
                if low:contact.append((row['sim_time'],b))
                else:
                    if len(contact)>=2 and contact[-1][0]-contact[0][0]>=.15:
                        slips.append({'duration_s':contact[-1][0]-contact[0][0],
                                      'horizontal_displacement_m':math.dist(contact[0][1][:2],contact[-1][1][:2]),'joint':tag})
                    contact=[]
        step['toe_contact_proxy_segments']=slips
        steps.append(step)
    result={'run_id':directory.name,'steps':steps,
        'position_measurement':'actual Behavior runtime root position',
        'speed_measurement':'finite difference of actual runtime position / actual sim time delta',
        'toe_contact_proxy_definition':{'max_height_m':.07,'max_vertical_speed_mps':.1,'min_duration_s':.15},
        'limitations':['Toe height proxy is not a force/contact sensor. Inspect continuous close-up video too.',
                      'A task marked succeeded in an early invalid run does not make it accepted.']}
    (directory/'validation_measurements.json').write_text(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args()
    r=analyze(args.directory);print(json.dumps({'run_id':r['run_id'],'completed_steps':len(r['steps'])}))
