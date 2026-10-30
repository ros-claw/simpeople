"""Independently compare final decoded demo timing with measured source frames."""
import argparse
import json
from pathlib import Path
import subprocess

p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--single',action='store_true');a=p.parse_args()
d=Path(a.directory);name='single_demo_manifest.json' if a.single else 'demo_manifest.json'
m=json.loads((d/name).read_text());stamps=[json.loads(line) for line in (d/'video_timestamps.jsonl').open()]
wall=[s['wall_time']-stamps[0]['wall_time'] for s in stamps]
audits=[m['frame_audit']] if a.single else [s['frame_audit'] for s in m['sections']]
expected=[];offset=0
for audit in audits:
    lo=audit['source_first_frame'];hi=audit['source_end_frame_exclusive']
    expected.extend(offset+x-wall[lo] for x in wall[lo:hi]);offset+=audit['duration_s']
probe=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames',
           '-show_entries','frame=best_effort_timestamp_time','-of','json',str(d/m['output'])],text=True)
actual=[float(f['best_effort_timestamp_time']) for f in json.loads(probe)['frames']]
error=max((abs(x-y) for x,y in zip(expected,actual)),default=float('inf'))
result={'passed':len(expected)==len(actual) and error<.005,'output':m['output'],
        'expected_source_frames':len(expected),'decoded_output_frames':len(actual),
        'max_decoded_wall_timestamp_error_s':error,'allowed_error_s':.005,
        'method':'ffprobe decoded frame timestamps versus measured source frame intervals and explicit segment durations; no encoding FPS assumption'}
(d/('single_timing_audit.json' if a.single else 'demo_timing_audit.json')).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
if not result['passed']:raise SystemExit(1)
