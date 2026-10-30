"""Cache the official Behavior sample and all USD/texture dependencies.

Uses system Python with usd-core, never installs dependencies in Isaac.
Each file is recorded with its source URL and SHA256. Existing content is checked.
"""
import concurrent.futures
import hashlib
import json
import posixpath
from pathlib import Path
import urllib.parse
import urllib.request
import time
from pxr import Sdf

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'assets/cache/behavior'
BASE = 'https://omniverse-content-staging.s3.us-west-2.amazonaws.com/Assets/Behavior/110.0/Samples/Assets/'

def fetch(rel):
    path = DEST / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        for attempt in range(3):
            try:
                data = urllib.request.urlopen(BASE + urllib.parse.quote(rel), timeout=60).read()
                temp = path.with_suffix(path.suffix+'.part')
                temp.write_bytes(data)
                temp.replace(path)
                break
            except Exception:
                if attempt == 2: raise
                time.sleep(attempt+1)
    refs = set()
    if path.suffix in {'.usd', '.usda', '.usdc'}:
        layer = Sdf.Layer.FindOrOpen(str(path))
        refs.update(layer.GetExternalReferences())
        def visit(p):
            spec = layer.GetObjectAtPath(p)
            if isinstance(spec, Sdf.AttributeSpec):
                v=spec.default
                if isinstance(v,Sdf.AssetPath): refs.add(v.path)
                elif spec.typeName == Sdf.ValueTypeNames.AssetArray and v:
                    refs.update(a.path for a in v)
        layer.Traverse('/',visit)
    deps=[]
    for ref in refs:
        if not ref or ref.endswith('.mdl'): continue
        if ref.startswith(BASE): rel2=urllib.parse.unquote(ref[len(BASE):])
        elif '://' in ref or ref.startswith('/'): continue
        else: rel2=posixpath.normpath(posixpath.join(posixpath.dirname(rel),ref))
        if rel2.startswith('../'): raise ValueError('Dependency outside cache: '+ref)
        deps.append(rel2)
    return {'path':rel,'source_uri':BASE+urllib.parse.quote(rel),'bytes':path.stat().st_size,
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},deps

def main():
    pending={'Characters/Human/Default.usd','MotionLibrary/Human/HumanMotionLibrary.usd'}
    seen=set(); manifest=[]; errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        while pending:
            batch=pending-seen; pending=set(); seen.update(batch)
            futures={pool.submit(fetch,r):r for r in batch}
            for f in concurrent.futures.as_completed(futures):
                try:
                    record,deps=f.result(); manifest.append(record); pending.update(deps)
                except Exception as e: errors.append({'path':futures[f],'error':str(e)})
            print(f'Cached {len(manifest)} files; discovered {len(pending-seen)} more; errors {len(errors)}',flush=True)
    result={'source':BASE,'license_note':'NVIDIA sample assets; reference locally, not redistributed.',
            'files':sorted(manifest,key=lambda a:a['path']),'errors':errors}
    (ROOT/'reports/asset_cache_manifest.json').write_text(json.dumps(result,indent=2))
    if errors: raise SystemExit(json.dumps(errors))

if __name__=='__main__':main()
