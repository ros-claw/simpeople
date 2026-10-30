"""Stream real evidence into a population/performance/trajectory acceptance report."""
import argparse
from collections import Counter,defaultdict
import json
import math
from pathlib import Path
import statistics

def quantile(values,q=.95):
    return sorted(values)[min(len(values)-1,int(q*len(values)))] if values else None

def summarize(directory):
    d=Path(directory);config=json.loads((d/'config.json').read_text());metrics=json.loads((d/'metrics.json').read_text())
    tasks=json.loads((d/'tasks.json').read_text());population=json.loads((d/'population.json').read_text()) if (d/'population.json').exists() else {}
    assets={a['asset_id']:a for a in json.loads((d/'asset_manifest.json').read_text())}
    end=json.loads((d/'measurement_end_state.json').read_text()) if (d/'measurement_end_state.json').exists() else None
    actor_data={};previous={};origins={};current={};group_time=None;overlaps={};segments=[];jumps=[];stationary_since={}
    minimum_separation={'distance_m':None}
    def process_frame(frame,now):
        ids=list(frame)
        contacts=set()
        for i,a in enumerate(ids):
            for b in ids[i+1:]:
                one,two=frame[a],frame[b]
                if not one.get('ready') or not two.get('ready'):continue
                p,q=one['position_m'],two['position_m']
                ra=assets.get(one['asset_id'],{}).get('runtime_radius_m',.25)
                rb=assets.get(two['asset_id'],{}).get('runtime_radius_m',.25)
                distance=math.dist(p[:2],q[:2]);pair=tuple(sorted([a,b]));threshold=.8*(ra+rb)
                if abs(p[2]-q[2])<.8 and (minimum_separation['distance_m'] is None or distance<minimum_separation['distance_m']):
                    minimum_separation.update(distance_m=distance,actors=pair,sim_time=now,radii_sum_m=ra+rb,overlap_proxy_threshold_m=threshold)
                if abs(p[2]-q[2])<.8 and distance<threshold:
                    contacts.add(pair)
                    segment=overlaps.setdefault(pair,{'actors':pair,'start_sim_time':now,'end_sim_time':now,'min_distance_m':distance,'threshold_m':threshold})
                    segment['end_sim_time']=now;segment['min_distance_m']=min(segment['min_distance_m'],distance)
        for pair in list(overlaps):
            if pair not in contacts:
                segment=overlaps.pop(pair)
                if segment['end_sim_time']-segment['start_sim_time']>=.3:segments.append(segment)
    for line in (d/'trajectories.jsonl').open():
        row=json.loads(line);now=row['sim_time'];aid=row['actor_id']
        if group_time is not None and now!=group_time:process_frame(current,group_time);current={}
        group_time=now;current[aid]=row
        data=actor_data.setdefault(aid,{'distance_travelled_m':0,'max_displacement_from_episode_start_m':0,'max_planar_speed_mps':0,'ready_samples':0,
                       'asset_id':row.get('asset_id'),'base_identity_id':row.get('base_identity_id'),'appearance_id':row.get('appearance_id'),
                       'moving_sim_s':0,'stationary_sim_s':0,'max_contiguous_stationary_sim_s':0,'native_action_time_sim_s':{}})
        if not row.get('ready'):continue
        if aid not in origins or origins[aid][0]!=row['episode_id']:
            origins[aid]=(row['episode_id'],row['position_m'])
        data['max_displacement_from_episode_start_m']=max(data['max_displacement_from_episode_start_m'],
            math.dist(row['position_m'][:2],origins[aid][1][:2]))
        data['ready_samples']+=1;before=previous.get(aid)
        if before and before['episode_id']==row['episode_id'] and now>before['sim_time']:
            dt=now-before['sim_time'];distance=math.dist(row['position_m'][:2],before['position_m'][:2])
            data['distance_travelled_m']+=distance;data['max_planar_speed_mps']=max(data['max_planar_speed_mps'],distance/dt)
            if distance>5*dt+.15:jumps.append({'actor_id':aid,'sim_time':now,'distance_m':distance,'dt_s':dt})
            action=before.get('action','unknown');times=data['native_action_time_sim_s'];times[action]=times.get(action,0)+dt
            speed=before.get('planar_speed_mps',math.hypot(*before.get('velocity_mps',[0,0])[:2]))
            if speed>.15:data['moving_sim_s']+=dt;stationary_since.pop(aid,None)
            else:
                data['stationary_sim_s']+=dt;stationary_since.setdefault(aid,before['sim_time'])
                data['max_contiguous_stationary_sim_s']=max(data['max_contiguous_stationary_sim_s'],now-stationary_since[aid])
        else:stationary_since.pop(aid,None)
        previous[aid]=row
    if current:process_frame(current,group_time)
    for segment in overlaps.values():
        if segment['end_sim_time']-segment['start_sim_time']>=.3:segments.append(segment)
    statuses=Counter(t['status'] for t in tasks);failures=Counter(t['error']['code'] for t in tasks if t['status']=='failed')
    shutdown_cancel=[t for t in tasks if t['status']=='cancelled' and t.get('error',{}).get('message')=='process_shutdown']
    cycles={a:p['cycle'] for a,p in population.items()};suspended=[a for a,p in population.items() if p['suspended']]
    resources=[json.loads(line) for line in (d/'resources.jsonl').open()] if (d/'resources.jsonl').exists() else []
    latencies=[];event_counts=Counter()
    for line in (d/'events.jsonl').open():
        e=json.loads(line)
        event_counts[e['kind']]+=1
        if e['kind']=='command_applied':latencies.append(e['wall_time']-e['received_wall_time'])
    instance_count=len(actor_data);requested=config.get('people',instance_count)
    required={10:600,30:900,50:600,100:120}.get(requested,config.get('duration',0))
    is_population=config.get('scenario')=='industrial_life' and not config.get('serve')
    full_time=metrics['sim_elapsed_s']+1/30+1e-5>=required
    participation=sum(v['max_displacement_from_episode_start_m']>1 for v in actor_data.values())
    richness={'instances':instance_count,'moving_participants':participation,
              'base_identities':len({v['base_identity_id'] for v in actor_data.values()}),
              'appearances':len({(v['base_identity_id'],v['appearance_id']) for v in actor_data.values()}),
              'role_types':len({p['role'] for p in population.values()})}
    targets={10:(4,8,4),30:(8,16,6),50:(12,24,6)};rich=targets.get(requested)
    richness_met=not rich or all(richness[k]>=v for k,v in zip(['base_identities','appearances','role_types'],rich))
    correctness=(is_population and requested<100 and instance_count==requested and full_time and
                 len(cycles)==requested and min(cycles.values(),default=0)>=1 and not suspended and
                 not jumps and not segments and richness_met and participation==requested)
    result={'run_id':d.name,'scope':'population gate' if is_population else 'control/asset run',
        'configuration':{k:config.get(k) for k in ['scenario','people','seed','gpu','width','height','no_video']},
        'richness':richness,'target_sim_seconds':required,'full_duration_met':full_time,
        'role_cycles_per_actor':cycles,'minimum_role_cycles':min(cycles.values(),default=0),'suspended_actors':suspended,
        'task_status_counts':dict(statuses),'failures_by_code':dict(failures),'shutdown_cancellations':len(shutdown_cancel),
        'at_measurement_cutoff_status_counts':dict(Counter(a['task']['status'] for a in end['actors'] if a['task'])) if end else None,
        'trajectory_proxies':{'definition':'horizontal runtime root capsules overlap if distance < 0.8*(runtime radii sum), same-floor dz<0.8m, continuous >=0.3s; not exact mesh penetration',
            'sustained_overlap_segments':segments,'root_discontinuities':jumps,'jump_definition':'horizontal displacement > 5m/s*actual_dt +0.15m',
            'minimum_same_floor_root_separation':minimum_separation},
        'performance':{k:metrics.get(k) for k in ['rtf','overall_rtf','sim_elapsed_s','wall_elapsed_s','measurement_wall_s','warmup_target_wall_s',
            'measured_updates_per_wall_second','frame_time_median_s','frame_time_p95_s','stage_time_medians_s']},
        'resources':{'max_process_rss_gib':max((r['process_rss_bytes']/1024**3 for r in resources),default=None),
            'median_process_cpu_percent':statistics.median([r['process_cpu_percent'] for r in resources]) if resources else None,
            'max_gpu_total_used_mib':max((r.get('gpu_total_used_mib',0) for r in resources),default=None),
            'gpu_note':'device totals include unrelated concurrent jobs; process RSS is this Kit process'},
        'bridge_latency_p95_wall_s':quantile(latencies),'actor_measurements':actor_data,
        'moving_participant_definition':'Actual ready runtime root displaced >1m from its first ready position within an episode. Cumulative idle sway and episode reset relocation cannot establish participation.',
        'participation_time_definition':'Left-sample integration of actual runtime planar speed >0.15m/s. Stationary includes deliberate waits, sitting, traffic and transitions; native action durations are separate. Not an exact congestion or foot-contact classifier.',
        'event_counts':dict(event_counts),'native_route_retry_events':event_counts.get('traffic_native_retry',0),
        'functional_population_gate_passed':correctness,'pressure_exploration_only':requested==100,
        'performance_target_met':((metrics['rtf']>=.8 and metrics.get('measured_updates_per_wall_second',0)>=24) if requested==30
                                  else metrics['rtf']>=.9 if requested in {1,10} else None),
        'limitations':['Population gate includes duration, per-actor cycles, richness and root geometry proxies; inspect native failure details and video too.',
                      'Proxy overlap checks cannot certify exact mesh collision or robot sensor visibility.',
                      'Failures and bounded recoveries remain in raw evidence even if all actors eventually complete cycles.']}
    (d/'acceptance_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args();result=summarize(args.directory)
    print(json.dumps({k:result[k] for k in ['run_id','richness','minimum_role_cycles','suspended_actors','functional_population_gate_passed']},indent=2))
