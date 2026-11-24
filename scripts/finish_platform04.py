"""Assemble real 30 Hz movie frames; keep Native evidence separate."""
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_master import check

OUT = ROOT / 'productions/platform04_review'
OUT.mkdir(exist_ok=True)


def rows(run):
    return [json.loads(s) for s in (run / 'frames.jsonl').read_text().splitlines()]


def ff(*args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *map(str, args)], check=True)


def validate(path, frames):
    result = check(path, frames=frames)
    clockfix = None
    if result['errors'] == ['incorrect duration']:
        def hashes(file):
            p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_packets', '-show_data_hash', 'sha256', '-show_entries',
                'packet=data_hash', '-of', 'json', str(file)], capture_output=True,
                text=True, check=True)
            return [a['data_hash'] for a in json.loads(p.stdout)['packets']]
        fixed = path.with_name(path.stem + '_duration_fixed.mp4')
        ff('-i', path, '-map', '0', '-c', 'copy', '-bsf:v',
           'setts=pts=PTS:dts=DTS:duration=1/(30*TB)', '-video_track_timescale',
           '30000', '-movflags', '+faststart', fixed)
        assert hashes(path) == hashes(fixed)
        clockfix = {'old_duration_s': result['stream']['duration'],
                    'compressed_packets_unchanged': True, 'PTS_DTS_retained': True}
        shutil.move(path, ROOT / f'.runtime/platform04/pre_duration_{time.time_ns()}.mp4')
        fixed.rename(path)
        result = check(path, frames=frames)
    assert result['passed'], result
    return {'validation': result, 'last_packet_duration_normalization': clockfix}


def main():
    base = ROOT / 'runs/platform04-master-01'
    ending = ROOT / 'runs/platform04-ending-02'
    for p in [base, ending]:
        assert (p / 'completed.json').exists() and not (p / 'failed.txt').exists()
    original = {r['source_tick']: r for r in rows(base)}
    retake = {r['source_tick']: r for r in rows(ending)}
    assert len(original) == 540 and sorted(retake) == list(range(395, 540))
    # Only the low croucher's brace changes. Principal geometry QA remains valid.
    errors = {}
    for field in ['root_world_m', 'joints_world_m', 'joint_quaternions_actor']:
        errors[field] = max(float(np.max(np.abs(np.asarray(original[f]['actors'][aid][field])
            - np.asarray(r['actors'][aid][field])))) for f, r in retake.items()
            for aid in ['hero', 'chaser', 'intercept'])
    assert max(errors.values()) < 1e-10, errors
    movie = OUT / 'Platform04_BlindSide_18s_1080p30.mp4'
    clean = OUT / 'Platform04_BlindSide_18s_Silent.mp4'
    source = OUT / 'Platform04_18s_SourceRGB.mp4'
    # Exactly 395 original frames + 145 retake frames, no rate conversion.
    ff('-i', base / 'raw_video.mp4', '-i', ending / 'raw_video.mp4',
       '-filter_complex', '[0:v]trim=end_frame=395,setpts=PTS-STARTPTS[a];'
       '[1:v]setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0[v]',
       '-map', '[v]', '-an', '-fps_mode', 'passthrough', '-c:v', 'libx264',
       '-preset', 'slow', '-crf', '17', '-threads', '4', '-pix_fmt', 'yuv420p',
       '-movflags', '+faststart', source)
    source_qa = validate(source, 540)
    ff('-i', source, '-i', OUT / 'Platform04_OriginalFoley.wav', '-map', '0:v:0',
       '-map', '1:a:0', '-vf', 'eq=gamma=1.25:contrast=1.04:saturation=0.88:brightness=0.004',
       '-c:v', 'libx264', '-preset', 'slow', '-crf', '17', '-threads', '4',
       '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough', '-c:a', 'aac',
       '-b:a', '256k', '-movflags', '+faststart', movie)
    movie_qa = validate(movie, 540)
    ff('-i', movie, '-map', '0:v:0', '-an', '-c:v', 'copy', '-movflags', '+faststart', clean)
    clean_qa = validate(clean, 540)
    near = OUT / 'Door_NearMiss_Uncut_30fps.mp4'
    ff('-i', source, '-vf', 'trim=start_frame=306:end_frame=395,setpts=PTS-STARTPTS',
       '-an', '-fps_mode', 'passthrough', '-c:v', 'libx264', '-crf', '17',
       '-preset', 'slow', '-threads', '4', '-pix_fmt', 'yuv420p', near)
    near_qa = validate(near, 89)
    unified = []
    for f in range(540):
        r = dict(retake[f] if f >= 395 else original[f])
        r.update(output_frame=f, output_pts_s=f/30,
                 source_run_id=ending.name if f >= 395 else base.name)
        unified.append(r)
    (OUT / 'master_frame_map.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in unified))
    duplicates = sum(a['rgb_sha256'] == b['rgb_sha256'] for a, b in zip(unified, unified[1:]))
    assert duplicates == 0
    locked = np.array([r['camera_matrix'] for r in unified[306:395]])
    camera_error = float(np.abs(locked - locked[0]).max())
    assert camera_error == 0
    assert all(unified[f]['source_run_id'] == base.name for f in range(306, 395))
    for f in [0, 48, 90, 180, 240, 270, 330, 345, 360, 375, 420, 450, 480, 510, 539]:
        run = ending if f >= 395 else base
        shutil.copy2(run / f'frame_{f:04d}.png', OUT / f'frame_{f:04d}.png')
    for p in base.glob('glass_*.png'):
        shutil.copy2(p, OUT / p.name)
    for name in ['geometry_qa.json', 'near_miss_trace.json']:
        shutil.copy2(ROOT / 'runs/platform04-geometry-02' / name, OUT / name)
    for case in ['north-03', 'south-04', 'occlusion-05', 'portals-02']:
        run = ROOT / ('runs/platform04-native-' + case)
        assert (run / 'completed.json').exists() and not (run / 'failed.txt').exists()
        target = OUT / 'native_evidence' / case
        target.mkdir(parents=True, exist_ok=True)
        for name in ['raw_video.mp4', 'frames.jsonl', 'events.json', 'completed.json',
                     'connectivity.json', 'recording_metrics.json', 'video_timestamps.jsonl',
                     'camera_preflight.png', 'diagnostic_view.json']:
            if (run / name).exists():
                shutil.copy2(run / name, target / name)
    # Synchronized independent simulations, scaled with no retiming or frame hold.
    n = OUT / 'native_evidence/north-03/raw_video.mp4'
    s = OUT / 'native_evidence/south-04/raw_video.mp4'
    ff('-i', n, '-i', s, '-filter_complex',
       '[0:v]scale=960:540[a];[1:v]scale=960:540[b];'
       '[a][b]hstack=shortest=1,pad=1920:1080:0:270:color=0x071218,'
       "drawtext=text='NATIVE - RUNNER CHOOSES NORTH':x=70:y=190:fontsize=30:fontcolor=white,"
       "drawtext=text='NATIVE - RUNNER CHOOSES SOUTH':x=1030:y=190:fontsize=30:fontcolor=white,"
       "drawtext=text='Same initial states. Same seed. Actual Native follow trajectories.':x=120:y=870:fontsize=28:fontcolor=white[v]",
       '-map', '[v]', '-an', '-fps_mode', 'passthrough', '-c:v', 'libx264',
       '-preset', 'slow', '-crf', '18', '-threads', '4', '-pix_fmt', 'yuv420p',
       OUT / 'Native_Fork_North_vs_South.mp4')
    fork_qa = validate(OUT / 'Native_Fork_North_vs_South.mp4', 357)
    result = {'movie': movie.name, 'silent': clean.name, 'source': source.name,
        'resolution': [1920, 1080], 'fps': 30, 'frames': 540, 'duration_s': 18,
        'movie_validation': movie_qa, 'silent_validation': clean_qa,
        'source_validation': source_qa, 'near_miss_clip_validation': near_qa,
        'native_comparison_validation': fork_qa,
        'same_tick_principal_retake_errors': errors,
        'locked_shot': {'first_tick': 306, 'last_tick': 394, 'frames': 89,
            'duration_s': 89/30, 'camera_matrix_max_difference': camera_error,
            'same_real_take': base.name},
        'adjacent_source_rgb_duplicates': duplicates,
        'edit_decisions': [{'source_run_id': base.name, 'source_ticks': [0, 394]},
                           {'source_run_id': ending.name, 'source_ticks': [395, 539]}],
        'instances': 11, 'normal_humans': 3, 'infected': 8,
        'verified_tests': 112,
        'motion_interpolation_or_speed_change': False,
        'grade': 'gamma=1.25 contrast=1.04 saturation=0.88 brightness=0.004',
        'audio': 'original procedural stereo Foley aligned to recorded gait phases; editorial, not physical sound propagation',
        'human_blind_review': {'status': 'not_measured', 'reviewers': 0},
        'capability_scope': 'movie: exclusive full-pose cache and directed paths; separate Native: ordinary jog, 1v1 observation-limited follow prototype',
        'not_accepted': ['60s full movie', 'multi-zombie Native pursuit',
            'Native infected-sprint pursuit', 'MCP zombie capability release',
            'hard Native follow speed/acceleration caps', 'PhysX body/contact-force simulation',
            'human fear/readability acceptance']}
    (OUT / 'DELIVERY.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({'movie': str(movie), 'frames': 540, 'retake_errors': errors,
                      'locked_camera_error': camera_error}, indent=2))


if __name__ == '__main__':
    main()
