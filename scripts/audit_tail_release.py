"""Independently audit corridor removals against recorded native roots/cell boxes."""
import argparse
import json
import math
from pathlib import Path


def actor_id(agent_path):
    # Both legacy and incarnation-scoped native paths retain Actors/<id>.
    # Do not use a fixed distance from SkelRoot: that now selects Instance_*.
    parts=agent_path.split('/')
    return parts[parts.index('Actors')+1]


def audit(directory):
    folder=Path(directory)
    def read(name):return json.loads((folder/name).read_text())
    done=read('benchmark_done.json');events=[]
    for line in (folder/'events.jsonl').open():
        e=json.loads(line)
        if e.get('cursor',0)<=done['event_cursor']:events.append(e)
    grid=next(e for e in events if e['kind']=='traffic_grid_ready');cell=grid['cell_m'];half=cell/2
    releases=[e for e in events if e['kind']=='traffic_tail_released'];brakes=[e for e in events if e['kind']=='traffic_tail_safety_brake']
    samples={};wanted={(round(e['sim_time'],7),actor_id(e['agent'])) for e in releases}
    for line in (folder/'trajectories.jsonl').open():
        row=json.loads(line);key=(round(row['sim_time'],7),row['actor_id'])
        if key in wanted:samples[key]=row
    starts={(e['route_id'],e['native_task_id']):e for e in events if e['kind']=='traffic_native_started' and e.get('action')=='continuous_corridor'}
    previous={};identities={};checks=[];errors=[];minimum=None
    for e in releases:
        key=(e['route_id'],e['native_task_id']);points=e['original_points_m'];start,end=points[0],points[-1]
        dx,dy=end[0]-start[0],end[1]-start[1];length=math.hypot(dx,dy);ux,uy=dx/length,dy/length
        root=e['position_m'];progress=(root[0]-start[0])*ux+(root[1]-start[1])*uy
        removed={tuple(c) for c in e['removed_cells']};remaining={tuple(c) for c in e['remaining_cells']}
        old=previous.get(key)
        begin=starts.get(key)
        if begin is None or begin['cursor']>=e['cursor'] or begin['points_m']!=points:
            errors.append({'cursor':e['cursor'],'reason':'no_matching_native_corridor_start'})
        elif old is None and len(removed|remaining)!=begin['reserved_cells']:
            errors.append({'cursor':e['cursor'],'reason':'initial_claim_count_changed'})
        if old is not None and (not removed<=old or old-removed!=remaining):errors.append({'cursor':e['cursor'],'reason':'claim_not_monotonic'})
        if not removed:errors.append({'cursor':e['cursor'],'reason':'empty_release'})
        if removed & remaining:errors.append({'cursor':e['cursor'],'reason':'removed_still_claimed'})
        if identities.setdefault(key,e['body_instance_id'])!=e['body_instance_id']:errors.append({'cursor':e['cursor'],'reason':'body_generation_changed'})
        previous[key]=remaining
        sample=samples.get((round(e['sim_time'],7),actor_id(e['agent'])))
        if sample is None or math.dist(sample['position_m'],root)>1e-5:errors.append({'cursor':e['cursor'],'reason':'no_matching_actual_root'})
        if sample is not None and sample.get('traffic',{}).get('native_task_id')!=e['native_task_id']:errors.append({'cursor':e['cursor'],'reason':'native_task_mismatch'})
        if sample is not None and sample.get('actor_instance_id')!=e['actor_instance_id']:errors.append({'cursor':e['cursor'],'reason':'actor_incarnation_mismatch'})
        margin=grid['footprint_margin_m']
        for label,p in [('body',root),('goal',end)]:
            footprint={(x,y) for x in range(math.floor((p[0]-margin)/cell+.5),math.floor((p[0]+margin)/cell+.5)+1)
                for y in range(math.floor((p[1]-margin)/cell+.5),math.floor((p[1]+margin)/cell+.5)+1)}
            if not footprint<=remaining:errors.append({'cursor':e['cursor'],'reason':label+'_footprint_not_retained'})
        for x,y in removed:
            cx,cy=x*cell,y*cell
            forward=max((cx+sx*half-start[0])*ux+(cy+sy*half-start[1])*uy for sx in [-1,1] for sy in [-1,1])
            gap=progress-forward
            distance=math.hypot(max(abs(root[0]-cx)-half,0),max(abs(root[1]-cy)-half,0))
            if gap<e['trail_m']+.05-1e-6:errors.append({'cursor':e['cursor'],'cell':[x,y],'reason':'released_inside_trailing_plane','gap_m':gap})
            if minimum is None or distance<minimum['distance_m']:minimum={'distance_m':distance,'cursor':e['cursor'],'cell':[x,y]}
        checks.append({'cursor':e['cursor'],'actor_id':actor_id(e['agent']),'sim_time':e['sim_time'],
            'removed_cells':len(removed),'remaining_cells':len(remaining),'progress_m':progress})
    counts={}
    for e in events:
        if e['kind']=='traffic_tail_tracking':
            reason='eligible' if e['eligible'] else e['reason'];counts[reason]=counts.get(reason,0)+1
    return {'run_id':folder.name,'enabled':read('runtime_contract.json')['runtime_policy']['tail_release_enabled'],
        'functional_expected_matched':read('completed.json')['functional_expected_matched'],'cutoff_event_cursor':done['event_cursor'],
        'tracking_counts':counts,'release_events':len(releases),'released_cell_count':sum(len(e['removed_cells']) for e in releases),
        'safety_brakes':brakes,'errors':errors,'proof_checks_passed':not errors and not brakes,
        'execution_observed':bool(releases),'execution_and_checks_passed':bool(releases) and not errors and not brakes,
        'minimum_actual_root_distance_to_released_cell_box':minimum,'checks':checks,
        'limits':['no releases means reclamation execution is unverified, even if proof_checks_passed is true',
            'geometric cell and native-root audit; no contact-force or exact mesh certification',
            'only same-generation active straight corridors within one grid row/column are eligible; curves, diagonals and high speeds retain full claims']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--output',required=True);args=parser.parse_args()
    result=audit(args.directory);Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['run_id','release_events','tracking_counts','proof_checks_passed','errors']},indent=2))
