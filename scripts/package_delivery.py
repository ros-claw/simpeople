"""Create separate source/evidence archives; never bundle downloaded character assets."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import time
ROOT=Path(__file__).resolve().parents[1]

def sha(path):
 digest=hashlib.sha256()
 with path.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
 return digest.hexdigest()

def package(run_ids):
 import tarfile
 dirty=subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)
 if dirty.strip():raise RuntimeError('Commit source/config/report changes before creating a reproducible source archive.')
 commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 out=ROOT/'dist';out.mkdir(exist_ok=True)
 source=out/f'rosclaw-simpeople-source-{commit[:12]}.tar.gz'
 subprocess.run(['git','archive','--format=tar.gz','--prefix=rosclaw-simpeople/','-o',str(source),commit],cwd=ROOT,check=True)
 files=[];runs=[]
 for run_id in run_ids:
  if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',run_id):raise ValueError('invalid run ID')
  directory=ROOT/'runs'/run_id
  if directory.is_symlink():raise ValueError('run directories must not be symlinks')
  if directory.parent!=ROOT/'runs' or not directory.is_dir():raise ValueError('invalid run ID: '+run_id)
  for name in ['ready.json','bootstrap.json']:
   try:
    pid=json.loads((directory/name).read_text())['pid'];cmd=Path(f'/proc/{pid}/cmdline').read_bytes()
    if b'kit_main.py' in cmd and run_id.encode() in cmd:raise RuntimeError('Refusing to archive an active run: '+run_id)
   except (FileNotFoundError,ProcessLookupError):pass
  runs.append({'run_id':run_id,'completed':(directory/'completion.json').exists()})
  for p in sorted(directory.rglob('*')):
   if p.is_file() and '__pycache__' not in p.parts:
    files.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)})
 evidence_manifest=out/'evidence_manifest.json'
 evidence_manifest.write_text(json.dumps({'runs':runs,'files':files,'models_included':False},indent=2)+'\n')
 evidence=out/'rosclaw-simpeople-evidence.tar.gz'
 with tarfile.open(evidence,'w:gz',compresslevel=2) as archive:
  archive.add(evidence_manifest,arcname='evidence_manifest.json')
  for entry in files:archive.add(ROOT/entry['path'],arcname=entry['path'],recursive=False)
 report={'git_commit':commit,'created_wall_time':time.time(),'runs':runs,
         'archives':[{'file':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in [source,evidence]],
         'external_assets':'Prepare the NVIDIA Behavior cache with scripts/cache_assets.py; original human USD assets remain in the user installation.',
         'restore':'Extract source archive, then extract evidence archive inside rosclaw-simpeople/. Follow README for environment/assets.'}
 (out/'delivery_manifest.json').write_text(json.dumps(report,indent=2)+'\n');return report

def verify(manifest):
 data=json.loads(Path(manifest).read_text());bad=[]
 for entry in data['files']:
  p=ROOT/entry['path']
  if not p.is_file() or sha(p)!=entry['sha256']:bad.append(entry['path'])
 if bad:raise RuntimeError('Evidence hash mismatch: '+', '.join(bad))
 return {'verified_files':len(data['files']),'passed':True}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--runs',nargs='+');parser.add_argument('--verify')
 args=parser.parse_args()
 if args.verify:result=verify(args.verify)
 elif args.runs:result=package(args.runs)
 else:parser.error('provide --runs or --verify')
 print(json.dumps(result,indent=2))
