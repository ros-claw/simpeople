"""Export an allowlisted source snapshot; never copy private history or assets."""
import argparse,hashlib,json,re,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DIRS={'src','scripts','configs','extensions','schemas','skills','plugins','docs','tests','.agents','.claude-plugin'}
FILES={'LICENSE','THIRD_PARTY.md','pyproject.toml','requirements-controller.txt','.gitignore'}
REPORTS={'reports/capability_matrix.json','reports/phase_gates.json','reports/REFERENCE_ACCEPTANCE.md','reports/OPTIMIZATION_20261031.md','reports/optimization_1031_gates.json','reports/optimization_1031_results.json','reports/optimization_1031_claude_status.json','reports/optimization_1031_plugin_installation.json','reports/optimization_1031_launcher_validation.json','reports/optimization_1031_final_performance.json'}
REPORTS|={'reports/optimization_1031_performance.json','reports/optimization_1031_optional_performance.json','reports/optimization_1031_interactive_performance.json'}
REPORTS|={'reports/SHIFT_CHANGE_20261101.json'}
ASSETS={'reports/optimization_1031_assets/seat_before.png','reports/optimization_1031_assets/seat_after.png','reports/optimization_1031_assets/media_manifest.json'}
ASSETS|={'reports/optimization_1031_assets/crowd50_media_manifest.json'}
p=argparse.ArgumentParser();p.add_argument('--destination',required=True);a=p.parse_args();destination=Path(a.destination).resolve()
if subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=ROOT).returncode:
 raise ValueError('commit the source changes before exporting a versioned snapshot')
if destination==ROOT or ROOT in destination.parents and not str(destination.relative_to(ROOT)).startswith('.runtime/'):
 raise ValueError('use a separate export directory or .runtime staging directory')
destination.mkdir(parents=True,exist_ok=True)
previous_file=destination/'SOURCE_MANIFEST.json'
previous=json.loads(previous_file.read_text()).get('files',{}) if previous_file.exists() else {}
paths=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=True).stdout.decode().split('\0')
manifest={}
for name in paths:
 if not name:continue
 rel=Path(name)
 if not (rel.parts[0] in DIRS or name in FILES or name in REPORTS or name in ASSETS):continue
 if rel.suffix in {'.docx','.pdf','.tar','.gz','.zip','.usd','.usda','.usdc','.usdz','.pyc'} or rel.suffix=='.mp4':continue
 if name=='docs/public_readme.md':continue
 source=ROOT/rel
 if source.is_symlink():raise ValueError('unexpected export symlink '+name)
 target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
 if name.startswith('reports/') and rel.suffix=='.md':
  text=target.read_text()
  text=re.sub(r'\[([^\]]+)\]\((?:\.\./)?(?:runs|dist)/[^)]+\)',r'`\1` (local reference evidence)',text)
  text=re.sub(r'\[([^\]]+)\]\((?:\.\./)?reports/(optimization_1031_[^/)]+\.mp4)\)',lambda m:'['+m[1]+'](https://github.com/ros-claw/simpeople/releases/download/'+('v0.2.0-preview' if m[2]=='optimization_1031_crowd50_demo.mp4' else 'demos-20261031')+'/'+m[2]+')',text)
  target.write_text(text)
 manifest[name]=hashlib.sha256(target.read_bytes()).hexdigest()
readme=ROOT/'docs/public_readme.md';shutil.copy2(readme,destination/'README.md');manifest['README.md']=hashlib.sha256(readme.read_bytes()).hexdigest()
(destination/'AGENTS.md').write_text('''# SimPeople development\n\nUse the configured Isaac installation; protocol tests do not establish native animation acceptance. Keep Kit imports in the native adapter, entry scripts and extension. All USD/Behavior mutations run on the Kit main thread. Preserve request idempotency, session/episode/controller generations, simulation-clock waits, cancellation settlement and resource cleanup. Do not teleport roots or add another bone writer to conceal failures.\n\nRun `PYTHONPATH=src python3 -m pytest -q tests`. Native acceptance also requires actual trajectories and continuous footage. Read `reports/REFERENCE_ACCEPTANCE.md`, `reports/OPTIMIZATION_20261031.md` and `docs/acceptance_criteria.md` before changing claims. Keep failed runs intact. Source inputs are frozen under each run's source_snapshot. Assets, caches, videos, runtime logs and credentials stay outside Git. Do not stop unrelated Isaac processes.\n''')
manifest['AGENTS.md']=hashlib.sha256((destination/'AGENTS.md').read_bytes()).hexdigest()
for old in previous.keys()-manifest.keys():
 target=destination/old
 if destination not in target.resolve().parents:raise ValueError('unsafe prior manifest path')
 if target.is_file():target.unlink()
result={'source_commit':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip(),
 'policy':'fresh source export, no existing Git history; no user planning documents, licensed asset data, runtime logs or credentials',
 'files':manifest}
(destination/'SOURCE_MANIFEST.json').write_text(json.dumps(result,indent=2));print(json.dumps({'destination':str(destination),'files':len(manifest),'bytes':sum((destination/n).stat().st_size for n in manifest)},indent=2))
