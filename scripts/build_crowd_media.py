"""Extract a continuous native crowd excerpt after the accepted run closes."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUN = 'opt1031-regression50-seed17-03'
directory = ROOT / 'runs' / RUN
summary = json.loads((directory / 'acceptance_summary.json').read_text())
assert summary['functional_population_gate_passed'], 'do not label an unaccepted crowd run as passed'
source = directory / 'raw_video.mp4'
output = ROOT / 'reports/optimization_1031_crowd50_demo.mp4'
manifest = ROOT / 'reports/optimization_1031_assets/crowd50_media_manifest.json'
assert not output.exists() and not manifest.exists(), 'preserve existing media and its provenance'

def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                             '-show_entries', 'stream=avg_frame_rate,nb_read_frames,width,height,start_time',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)['streams'][0]

def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()

# The recorder uses a constant 30 Hz simulation-time stream. Accurate input
# seeking decodes/discards to the selected timestamp before encoding the clip.
source_info = probe(source)
assert source_info['avg_frame_rate'] == '30/1' and float(source_info['start_time']) == 0
start_frame, frames = 9000, 750
assert int(source_info['nb_read_frames']) >= start_frame + frames
first_identity = None
last_identity = None
for line in (directory / 'frame_identity.jsonl').open():
    row = json.loads(line)
    if row['video_frame'] == start_frame:
        first_identity = row
    if row['video_frame'] == start_frame + frames - 1:
        last_identity = row
assert first_identity and last_identity
overlay = ('drawbox=x=0:y=0:w=iw:h=55:color=black@0.7:t=fill,'
           'drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:'
           'text=50 PEOPLE | native Isaac Sim | simulation-time playback:'
           'x=24:y=15:fontsize=25:fontcolor=white')
subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-n', '-ss', str(start_frame / 30),
                '-i', str(source), '-frames:v', str(frames), '-vf', overlay, '-an',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '21', '-threads', '4',
                '-movflags', '+faststart', str(output)], check=True)
output_info = probe(output)
assert int(output_info['nb_read_frames']) == frames and output_info['avg_frame_rate'] == '30/1'
data = {'run_id': RUN, 'continuous_excerpt': True,
        'source': str(source.relative_to(ROOT)),
        'source_sha256': digest(source),
        'start_frame_zero_based': start_frame, 'end_frame_exclusive': start_frame + frames,
        'first_frame_identity': first_identity, 'last_frame_identity': last_identity,
        'scope': '25 seconds of actual simulation-time rendering with title overlay; not wall-clock throughput',
        'files': [{'path': str(output.relative_to(ROOT)), 'bytes': output.stat().st_size,
                   'sha256': digest(output)}], 'probe': output_info}
manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2))
print(json.dumps(data, ensure_ascii=False, indent=2))
