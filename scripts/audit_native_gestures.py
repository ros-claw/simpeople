"""Audit direct native gesture trials without treating task acceptance as success."""
import argparse,json,sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from simpeople.core.gestures import measure,return_ready


def audit(folder):
    folder=Path(folder);phases=json.loads((folder/'gesture_phases.json').read_text());baseline=phases['baseline'];groups=defaultdict(list)
    for line in (folder/'gestures.jsonl').open():
        row=json.loads(line);groups[(row['actor_id'],row['phase'])].append(row)
    results=[]
    for (aid,name),rows in groups.items():
        if name.startswith('look_') or name.startswith(('left_','right_')):
            action='head_look' if name.startswith('look_') else 'reach_hand';hand=name.split('_')[0] if action=='reach_hand' else None
            phase=next(p for p in phases['phases'] if p['name']==name)
            base=phase.get('baseline',baseline)[aid]
            values=[measure(action,hand,r['target_m'],base,r) for r in rows if 1<=r['phase_time_s']<=2.4]
            results.append({'actor_id':aid,'phase':name,'action':action,'hand':hand,'samples':len(values),'all_aligned':bool(values) and all(v['aligned'] for v in values),
                'max_root_displacement_m':max(v['root_displacement_m'] for v in values),'max_root_turn_deg':max(v['root_facing_change_deg'] for v in values),
                'max_bone_length_deviation':max(v['bone_length_max_deviation'] for v in values),
                'max_target_error':max(v['head_angle_error_deg'] if action=='head_look' else v['hand_error_m'] for v in values)})
    returns={aid:all(return_ready('reach_hand','right',baseline[aid],r) for r in groups[(aid,'after_cancel')] if r['phase_time_s']>=1) for aid in baseline}
    return {'run_id':folder.name,'joint_proxy_audit_passed':all(r['all_aligned'] for r in results) and all(returns.values()),'trials':results,'cancel_hand_return':returns,
        'limits':['head direction is calibrated from neutral joint orientation and body facing; eye gaze is not measured','wrist distance and bone-length ratios do not prove skin contact, grasping or force','direct bindings exploration does not prove Engine cancellation and task arbitration']}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();result=audit(a.directory)
    (Path(a.directory)/'gesture_audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
