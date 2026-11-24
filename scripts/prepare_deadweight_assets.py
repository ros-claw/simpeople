"""Unpack the two user-supplied local kits without executing their scripts.

Existing extracted files are compared, never silently replaced. Assets remain
outside Git; this command does not download or redistribute licensed models.
"""
import hashlib,json,stat,subprocess,sys,zipfile
from pathlib import Path,PurePosixPath

ROOT=Path(__file__).resolve().parents[1]
destination=ROOT/'.runtime/deadweight';destination.mkdir(parents=True,exist_ok=True)
manifest={}
for name in ['Deadweight_Isaac_Codex_Production_Kit','Deadweight_Feasibility_Assets']:
    archive=ROOT/(name+'.zip')
    if not archive.is_file():raise SystemExit(f'Missing local user kit: {archive}')
    folder=destination/name;folder.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist())>2_000_000_000:raise ValueError('unexpected archive size')
        for info in z.infolist():
            member=PurePosixPath(info.filename)
            if member.is_absolute() or '..' in member.parts or stat.S_ISLNK(info.external_attr>>16):raise ValueError('unsafe ZIP member')
            target=folder.joinpath(*member.parts)
            if not target.resolve().is_relative_to(folder.resolve()):raise ValueError('unsafe extraction destination')
            if info.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            data=z.read(info)
            if target.exists():
                if hashlib.sha256(target.read_bytes()).digest()!=hashlib.sha256(data).digest():raise ValueError(f'preserving changed local file: {target}')
            else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    manifest[name]={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'directory':str(folder)}
(destination/'asset_sources.json').write_text(json.dumps(manifest,indent=2)+'\n')
prepared=destination/'prepared'
if not all((prepared/file).is_file() for file in ['zombie_skeleton.usdc','zombie_clip.usdc']):
    subprocess.run([sys.executable,str(ROOT/'scripts/prepare_deadweight_animation.py')],check=True)
else:
    print('Preserved existing normalized animation assets; import evidence remains valid.')
registry=ROOT/'configs/deadweight/actions.json'
if not registry.exists():
    registry.parent.mkdir(parents=True,exist_ok=True)
    registry.write_text(json.dumps({'schema_version':'simpeople.custom_actions.v1','actions':{'zombie_walk':{'label':'丧尸拖步试拍','skeleton':str(prepared/'zombie_skeleton.usdc'),'clip':str(prepared/'zombie_clip.usdc'),'clearance_radius_m':2}}},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
