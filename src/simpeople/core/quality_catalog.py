"""Quality claims are bound to concrete asset, action and seat revisions."""
import hashlib
import json
from pathlib import Path

SCHEMA='simpeople.quality-catalog.v1'

def hash_tree(directory):
    directory=Path(directory);digest=hashlib.sha256();count=0
    for path in sorted(directory.rglob('*')):
        if not path.is_file() or path.suffix not in {'.usd','.usda','.usdc'}:continue
        digest.update(path.relative_to(directory).as_posix().encode());digest.update(b'\0')
        digest.update(hashlib.sha256(path.read_bytes()).digest());count+=1
    return digest.hexdigest() if count else None

def tree_stamp(directory):
    root=Path(directory)
    return tuple((p.relative_to(root).as_posix(),p.stat().st_size,p.stat().st_mtime_ns)
                 for p in sorted(root.rglob('*')) if p.is_file() and p.suffix in {'.usd','.usda','.usdc'})

class QualityCatalog:
    def __init__(self,data=None):
        self.data=data or {'schema_version':SCHEMA,'records':[]}
        if self.data.get('schema_version')!=SCHEMA:raise ValueError('unsupported quality catalog schema')
    def query(self,asset_revision,motion_revision,rig_id,kind,seat_template=None,seat_geometry=None,runtime_revision=None):
        if not asset_revision or not motion_revision:return {'status':'unverified','revision_match':False,'reason':'resources unavailable'}
        for record in self.data.get('records',[]):
            if (record.get('asset_revision_sha256')==asset_revision and record.get('motion_revision_sha256')==motion_revision
                and record.get('rig_id')==rig_id and record.get('kind')==kind
                and record.get('runtime_revision')==runtime_revision
                and (kind!='seat' or (record.get('seat_template_sha256')==seat_template and record.get('seat_geometry_sha256')==seat_geometry))):
                return {**record,'revision_match':True}
        return {'status':'unverified','revision_match':False,'reason':'no audit for this exact asset, motion and interaction revision'}

def template_hash(profile):
    # Placement does not change the chair fit; surrounding scene obstacles are
    # still subject to independent runtime checks.
    data=dict(profile)
    for key in ('position_m','yaw_rad'):data.pop(key,None)
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':')).encode()).hexdigest()
