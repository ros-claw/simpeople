"""Evidence gates for a real take, independent of captions and model claims."""
import argparse,json,math,csv
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def analyze(directory):
    d=Path(directory);cfg=json.loads((d/'production_config.json').read_text());mode=cfg['mode']
    frames=[json.loads(x) for x in (d/'cinematic_frames.jsonl').open()]
    expected={'technical':900,'director':720,'master':2700}[mode]
    gates={'frame_count':len(frames)==expected,
           'video_indices':all(r['video_frame']==i and r['frame']==i for i,r in enumerate(frames)),
           'consecutive_simulation_ticks':all(b['source_tick']-a['source_tick']==1 for a,b in zip(frames,frames[1:])),
           'simulation_intervals':all(abs(b['sim_time']-a['sim_time']-1/30)<1e-6 for a,b in zip(frames,frames[1:]))}
    recording=json.loads((d/'recording_metrics.json').read_text());gates['recording_closed']=recording['frames_written']==expected and recording['empty_rgb_frames']==0 and recording['dropped_frames']==0
    result={'run_id':d.name,'mode':mode,'gates':gates,'recording':recording}
    if mode!='technical':
        applied=json.loads((d/'cinematic_agent_applied.json').read_text());tasks={t['task_id']:t for t in json.loads((d/'tasks.json').read_text())}
        heroes=('patrol_orange','patrol_blue');start=44*30 if mode=='master' else 8*30;end=68*30 if mode=='master' else 24*30
        core=[r for r in frames if start<=r['frame']<end]
        gates['core_uncut']=bool(core and all(not x['camera_cut'] for x in core[1:]) and len({tuple(r['eye_m']) for r in core})==1 and len({tuple(r['look_at_m']) for r in core})==1)
        gates['unchanged_at_agent_batch']=len(applied['untouched_at_batch'])==22 and all(applied['untouched_at_batch'].values())
        gates['waiter_original_task']=len({r['actors']['bench_waiter']['task_id'] for r in frames})==1
        gates['real_agent_tasks']=all(tasks[applied['tasks'][aid]]['source']=='agent' for aid in heroes)
        gates['only_targeted_agent_actors']={t['actor_id'] for t in tasks.values() if t['source']=='agent'}==set(heroes)
        calls=[]
        for line in (d/'codex_session.jsonl').open():
            try:r=json.loads(line)
            except ValueError:continue
            item=r.get('item',{})
            if r.get('type')=='item.completed' and item.get('type')=='mcp_tool_call':calls.append(item)
        gates['actual_host_tool_calls']=any(x.get('server')=='simpeople' and x.get('tool')=='people_crowd' for x in calls)
        before=frames[max(0,start-60)];after=core[-1]
        changes={aid:{'before_dx_m':frames[start-1]['actors'][aid]['position_m'][0]-before['actors'][aid]['position_m'][0],
                      'after_dx_m':after['actors'][aid]['position_m'][0]-frames[start]['actors'][aid]['position_m'][0]} for aid in heroes}
        gates['both_actual_direction_changes']=all(x['before_dx_m']<-.3 and x['after_dx_m']>.7 for x in changes.values())
        queue_motion={aid:max(math.dist(r['actors'][aid]['position_m'][:2],core[0]['actors'][aid]['position_m'][:2]) for r in core) for aid in ['queue_00','queue_01','queue_02']}
        gates['background_queue_moves']=max(queue_motion.values())>.5
        arrivals={aid:next((r['film_time_s'] for r in frames if r['actors'][aid]['task_id']==applied['tasks'][aid] and r['actors'][aid]['status']=='succeeded'),None) for aid in heroes}
        if mode=='master':gates['both_native_arrivals_before_80s']=all(t is not None and t<80 for t in arrivals.values())
        result.update(real_host_mcp_calls=len(calls),applied=applied,direction_changes=changes,queue_motion_m=queue_motion,native_arrival_film_s=arrivals)
        if mode=='master':
            seated=[];fine=[]
            for line in (d/'trajectories.jsonl').open():
                row=json.loads(line);index=row.get('frame_identity',{}).get('video_frame')
                if row['actor_id']!='seat_actor' or index is None or not 22*30<=index<33*30:continue
                if row.get('task_step_phase')=='holding':seated.append(index)
                value=row.get('seat_quality',{}).get('seat_00',{}).get('skinned_vertices')
                if value and value.get('available'):fine.append(value)
            gates['visible_window_seated_hold']=len(seated)>=30
            gates['seat_headneck_vertices']=bool(fine) and all(v['penetrating_vertices']==0 for v in fine)
            result['seat_window']={'holding_frames':len(seated),'fine_samples':len(fine),
                                   'min_vertex_clearance_m':min((v['front_plane_clearance_m'] for v in fine if v.get('front_plane_clearance_m') is not None),default=None)}
    with (d/'source_frame_map.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['output_frame','run_id','source_frame','source_tick','sim_time','wall_time','shot'])
        writer.writerows([r['frame'],d.name,r['video_frame'],r['source_tick'],r['sim_time'],r['wall_time'],r['shot']] for r in frames)
    result['passed']=all(gates.values());(d/'cinematic_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();r=analyze(a.directory);print(json.dumps(r,ensure_ascii=False,indent=2));raise SystemExit(0 if r['passed'] else 1)
