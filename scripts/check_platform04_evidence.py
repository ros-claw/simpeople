"""Read closed Kit runs and audit the counterfactual, not the movie route."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'productions/platform04_review'


def load(run, file):
    p = ROOT / 'runs' / ('platform04-' + run) / file
    return [json.loads(x) for x in p.read_text().splitlines()] if file.endswith('jsonl') else json.loads(p.read_text())


def main():
    north = load('native-north-03', 'frames.jsonl')
    south = load('native-south-04', 'frames.jsonl')
    initial = [load('native-' + b + ('-03' if b == 'north' else '-04'), 'completed.json') for b in ['north', 'south']]
    config = [load('native-' + b + ('-03' if b == 'north' else '-04'), 'bootstrap.json') for b in ['north', 'south']]
    assert config[0]['gpu'] == config[1]['gpu'] == 2
    assert initial[0]['actual_initial_states'] == initial[1]['actual_initial_states']
    common = min(len(north), len(south))
    hunter = [np.array([r['hunter']['position_m'] for r in case[:common]]) for case in [north, south]]
    divergence = np.linalg.norm(hunter[0] - hunter[1], axis=1)
    assert divergence[:30].max() == 0 and divergence[30:].max() > 2
    source_checks = {}
    for name in ['platform04_native_chase.py', 'src/simpeople/core/pursuit.py',
                 'src/simpeople/backends/native/platform04_scene.py',
                 'src/simpeople/backends/native/adapter.py']:
        hashes = []
        for b in ['north', 'south']:
            run_id = 'platform04-native-' + b + ('-03' if b == 'north' else '-04')
            p = ROOT / 'runs' / run_id / 'source_snapshot' / name
            hashes.append(hashlib.sha256(p.read_bytes()).hexdigest())
        assert hashes[0] == hashes[1], name
        source_checks[name] = hashes[0]
    pillar_positions = []
    for h in hunter:
        i = int(np.abs(h[:, 0] - 26).argmin())
        pillar_positions.append({'tick': i, 'position_m': h[i].tolist()})
    assert pillar_positions[0]['position_m'][1] > 5.3
    assert pillar_positions[1]['position_m'][1] < 3.5
    events = load('native-occlusion-05', 'events.json')
    transitions = [e for e in events if e['event'] == 'perception_state']
    assert [e['state'] for e in transitions] == ['PURSUE', 'LAST_SEEN', 'SEARCH', 'PURSUE']
    # SEARCH keeps the actual last seen point; it cannot follow the hidden actor.
    occ = load('native-occlusion-05', 'frames.jsonl')
    search = [r for r in occ if r['intent']['state'] == 'SEARCH']
    target = np.array([r['intent']['target_m'] for r in search])
    assert np.max(abs(target - target[0])) == 0
    assert all(r['intent']['observation_m'] is None for r in search)
    occ_setup = load('native-occlusion-05', 'completed.json')['occlusion_probe_setup']
    assert 'Idle until tick 75' in occ_setup
    assert transitions[-1]['tick'] < next(e['tick'] for e in events if e['event'] == 'runner_reemerges')
    portals = load('native-portals-02', 'completed.json')
    assert portals['passed'] and portals['native_completed_routes'] == 3
    portal_events = load('native-portals-02', 'events.json')
    finished = [e for e in portal_events if e['event'] == 'native_route_completed']
    assert len(finished) == 3
    portal_rows = load('native-portals-02', 'frames.jsonl')
    crossing = []
    for a, b in zip(portal_rows, portal_rows[1:]):
        p = np.array(a['observation']['position_m']);q = np.array(b['observation']['position_m'])
        if p[1] < -.248 <= q[1]:
            hit = p + (q-p)*(-.248-p[1])/(q[1]-p[1])
            crossing.append({'tick': b['source_tick'], 'position_m': hit.tolist()})
    assert len(crossing) == 1 and abs(crossing[0]['position_m'][0]-23) < 1.16
    with (OUT / 'native_fork_trajectories.csv').open('w') as f:
        w = csv.writer(f);w.writerow(['tick','relative_sim_s','north_runner_x','north_runner_y',
            'north_hunter_x','north_hunter_y','south_runner_x','south_runner_y',
            'south_hunter_x','south_hunter_y','hunter_divergence_m'])
        for i in range(common):
            w.writerow([i,i/30,*north[i]['runner']['position_m'][:2],*hunter[0][i,:2],
                *south[i]['runner']['position_m'][:2],*hunter[1][i,:2],divergence[i]])
    checks = {'passed': True, 'same_gpu_index': 2, 'same_actual_initial_states': initial[0]['actual_initial_states'],
        'same_source_sha256': source_checks, 'common_frames': common,
        'pre_branch_max_hunter_difference_m': float(divergence[:30].max()),
        'post_branch_max_hunter_difference_m': float(divergence[30:].max()),
        'max_difference_tick': int(divergence.argmax()),
        'hunter_positions_near_pillar_x26': dict(zip(['north','south'],pillar_positions)),
        'cancel_settled': {b: initial[i]['cancel_settled'] for i,b in enumerate(['north','south'])},
        'occlusion_state_transitions': transitions, 'occlusion_probe_setup': occ_setup,
        'search_target_max_drift_m': float(np.max(abs(target-target[0]))),
        'actual_native_portal_completions': finished, 'actual_car_side_crossing': crossing,
        'runtime': initial[0]['runtime'],
        'scope': 'formal Native ordinary jog, same station, 1v1 follow of an observation proxy at 3.75 Hz; geometric visibility with FOV/range/solid occlusion; no future path input',
        'limits': ['not learned or RGB-based perception', 'not infected Native sprint',
            'not multiple autonomous zombies', 'Native Follow speed/acceleration hard limits not accepted',
            'occlusion probe intentionally holds Native observer Idle for first 2.5s',
            'film near miss uses independent directed cache, not these Native trajectories']}
    assert all(checks['cancel_settled'].values())
    (OUT / 'native_pursuit_qa.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
    # Exported technical plot, preserving real metric axes and both trajectories.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    plt.rcParams.update({'font.size':10})
    fig,(ax,bx)=plt.subplots(2,1,figsize=(10,7),gridspec_kw={'height_ratios':[2,1]})
    for case,label,color in [(north,'North','#18798c'),(south,'South','#c45d3e')]:
        r=np.array([r['runner']['position_m'] for r in case]);h=np.array([r['hunter']['position_m'] for r in case])
        ax.plot(r[:,0],r[:,1],'--',color=color,lw=1.7,label=label+' runner')
        ax.plot(h[:,0],h[:,1],color=color,lw=2.2,label=label+' Native hunter')
    ax.add_patch(Rectangle((25.65,4.05),.7,.7,facecolor='#25343a'))
    ax.annotate('Solid pillar',(26,4.4),(26.7,3.8))
    ax.set(xlabel='World X (m)',ylabel='World Y (m)',title='Same initial states; only the runner changes sides')
    ax.axis('equal');ax.grid(alpha=.18);ax.legend(loc='upper left',ncol=2)
    bx.plot(np.arange(common)/30,divergence,color='#a23724');bx.axvline(1,color='#777',ls='--')
    bx.set(xlabel='Simulation time (s)',ylabel='Hunter separation (m)',title=f'Before branch: 0 m / after branch: {divergence.max():.3f} m maximum')
    bx.grid(alpha=.2);fig.tight_layout();fig.savefig(OUT/'native_fork_trajectories.png',dpi=170);plt.close(fig)
    print(json.dumps({k:checks[k] for k in ['passed','pre_branch_max_hunter_difference_m',
        'post_branch_max_hunter_difference_m','actual_car_side_crossing']},indent=2))


if __name__ == '__main__':
    main()
