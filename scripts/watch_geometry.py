"""Read-only trajectory audit; optionally stop this named run after three flags."""
import argparse,json,os
from pathlib import Path
import signal,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.core.quality import QualityAudit
p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--stop-on-three',action='store_true');args=p.parse_args()
d=Path(args.directory);audit=QualityAudit();frame={};stamp=None
with (d/'trajectories.jsonl').open() as stream:
 while True:
  line=stream.readline()
  if not line:
   if (d/'completion.json').exists():break
   time.sleep(.2);continue
  row=json.loads(line);now=row['sim_time']
  if stamp is not None and now!=stamp:
   assets=json.loads((d/'asset_manifest.json').read_text());radii={a['asset_id']:a.get('runtime_radius_m',.25) for a in assets}
   audit.tick(stamp,frame,radii);frame={}
   if audit.report()['critical_count']>=3:
    if args.stop_on_three:
     ready=json.loads((d/'ready.json').read_text());cmd=Path(f'/proc/{ready["pid"]}/cmdline').read_bytes()
     if b'kit_main.py' not in cmd:raise RuntimeError('PID identity changed; refusing signal')
     os.kill(ready['pid'],signal.SIGTERM)
    break
  stamp=now;frame[row['actor_id']]=row
(d/'live_geometry_audit.json').write_text(json.dumps(audit.report(),indent=2)+'\n')
print(json.dumps(audit.report(),indent=2))
