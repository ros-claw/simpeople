"""Bounded native clip acceptance; proxy geometry is not a physics certificate."""
import argparse,json,math
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def audit(run_id,accept=False):
    d=ROOT/'runs'/run_id
    tasks=json.loads((d/'tasks.json').read_text())
    cast={r['actor_id']:r for r in json.loads((d/'cinematic_cast.json').read_text())}
    assets={r['asset_id']:r for r in json.loads((d/'asset_manifest.json').read_text())}
    registry=json.loads((d/'custom_actions/registry.json').read_text())
    rows=defaultdict(list)
    for line in (d/'trajectories.jsonl').open():
        r=json.loads(line)
        if r.get('frame_identity',{}).get('video_frame') is not None:rows[r['actor_id']].append(r)
    result={};proofs={}
    for aid,info in cast.items():
        task=next(t for t in tasks if t['actor_id']==aid)
        name=task['steps'][0]['target'];clip=[r for r in rows[aid] if r.get('action')==name]
        feet=[r['joints_m'][f][2] for r in clip for f in ['LeftFoot','RightFoot'] if f in r.get('joints_m',{})]
        airborne=sum(min(r['joints_m'][f][2] for f in ['LeftFoot','RightFoot'])>.22 for r in clip)
        extent=max((math.dist(r['joints_m'][j][:2],r['position_m'][:2]) for r in clip for j in r.get('joints_m',{})),default=math.inf)
        moved=max((math.dist(r['position_m'][:2],info['spawn_m'][:2]) for r in rows[aid]),default=0)
        gates={'actual_clip_frames':len(clip)>=300,'native_activity_completed':task['status']=='succeeded',
               'returned_to_locomotion':moved>1,'foot_joint_floor_proxy':bool(feet) and min(feet)>=-.02,
               'recorded_joints_within_activity_radius':extent<registry[name]['clearance_radius_m']}
        result[name]={'actor_id':aid,'asset_id':info['asset_id'],'gates':gates,'passed':all(gates.values()),
                      'clip_frames':len(clip),'min_foot_joint_z_m':min(feet) if feet else None,
                      'both_feet_above_22cm_frames':airborne,'recorded_joint_radius_m':extent,'return_displacement_m':moved}
        if result[name]['passed']:
            proofs[name]={info['asset_id']:{'source_sha256':registry[name]['source_sha256'],
                'runtime_revision':registry[name]['runtime_revision'],'asset_sha256':assets[info['asset_id']]['content_hash'],
                'evidence':str(d.relative_to(ROOT)/'custom_action_audit.json'),
                'scope':'this clip, this asset, this runtime; native task, recorded joints and footage; no whole-mesh/contact-force certification'}}
    output={'run_id':run_id,'passed':all(r['passed'] for r in result.values()),'actions':result,
            'limitation':'Foot joint and recorded joint envelope proxies; not all vertices, contact forces, general parkour or arbitrary rigs.'}
    (d/'custom_action_audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2))
    if accept:
        assert output['passed'],'do not accept failed clips'
        (ROOT/'configs/custom_action_acceptance.json').write_text(json.dumps(proofs,ensure_ascii=False,indent=2)+'\n')
    return output


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run_id');p.add_argument('--accept',action='store_true');a=p.parse_args()
    r=audit(a.run_id,a.accept);print(json.dumps(r,ensure_ascii=False,indent=2));raise SystemExit(0 if r['passed'] else 1)
