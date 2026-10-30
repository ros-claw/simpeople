"""Verify archive bytes and every tar entry without extracting untrusted paths."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath
import subprocess
import tarfile

p=argparse.ArgumentParser();p.add_argument('--directory',default='dist');a=p.parse_args()
out=Path(a.directory);root=Path(__file__).resolve().parents[1]
delivery=json.loads((out/'delivery_manifest.json').read_text())
manifest=json.loads((out/'evidence_manifest.json').read_text())
expected={x['path']:x for x in manifest['files']}
def digest(stream,algorithm='sha256',prefix=b''):
    h=hashlib.new(algorithm);h.update(prefix)
    while block:=stream.read(1024*1024):h.update(block)
    return h.hexdigest()
def safe(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts:raise ValueError('unsafe archive path: '+name)
    return path

archive_checks=[]
for entry in delivery['archives']:
    with (out/entry['file']).open('rb') as stream:actual=digest(stream)
    if actual!=entry['sha256']:raise ValueError('archive SHA256 mismatch: '+entry['file'])
    archive_checks.append({'file':entry['file'],'sha256':actual,'passed':True})

seen=set()
with tarfile.open(out/'rosclaw-simpeople-evidence.tar.gz','r|gz') as archive:
    for member in archive:
        safe(member.name)
        if not member.isfile():raise ValueError('non-regular evidence member: '+member.name)
        stream=archive.extractfile(member)
        if member.name=='evidence_manifest.json':
            if json.load(stream)!=manifest:raise ValueError('embedded evidence manifest differs')
            continue
        if member.name not in expected or member.name in seen:raise ValueError('unexpected or duplicate evidence member')
        entry=expected[member.name]
        if member.size!=entry['bytes'] or digest(stream)!=entry['sha256']:raise ValueError('evidence member differs: '+member.name)
        seen.add(member.name)
if seen!=set(expected):raise ValueError('evidence members missing')

source=next(x['file'] for x in delivery['archives'] if '-source-' in x['file'])
git_entries={}
if (root/'.git').exists():
    listing=subprocess.check_output(['git','ls-tree','-rz','--full-tree',delivery['git_commit']],cwd=root)
    for row in listing.split(b'\0'):
        if row:
            header,path=row.split(b'\t',1);mode,kind,oid=header.split()
            git_entries[path.decode()]={'mode':mode.decode(),'oid':oid.decode()}
source_seen=set()
with tarfile.open(out/source,'r|gz') as archive:
    for member in archive:
        path=safe(member.name)
        if not path.parts or path.parts[0]!='rosclaw-simpeople':raise ValueError('wrong source prefix')
        relative=str(PurePosixPath(*path.parts[1:]))
        if any(x in path.parts for x in ['.git','.runtime','.venv-controller']) or 'assets/cache/' in relative:raise ValueError('runtime/cache leaked into source')
        if member.isdir():continue
        if relative in source_seen:raise ValueError('duplicate source member')
        source_seen.add(relative)
        if not member.isfile():raise ValueError('unexpected source link/special file')
        if git_entries:
            entry=git_entries.get(relative)
            if entry is None:raise ValueError('source member absent from recorded Git commit')
            algorithm='sha1' if len(entry['oid'])==40 else 'sha256'
            actual=digest(archive.extractfile(member),algorithm,f'blob {member.size}\0'.encode())
            if actual!=entry['oid']:raise ValueError('source member differs from Git blob: '+relative)
if git_entries and source_seen!=set(git_entries):raise ValueError('source members missing from archive')
result={'passed':True,'git_commit':delivery['git_commit'],'archives':archive_checks,
        'evidence_files_verified_inside_archive':len(seen),'source_files_verified':len(source_seen),
        'source_git_blob_verification':bool(git_entries),'models_or_runtime_caches_in_source':False,
        'method':'Stream tar entries, compare embedded manifest and per-file SHA256; compare source content with recorded Git blob objects when repository is available. No extraction.'}
(out/'archive_verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
