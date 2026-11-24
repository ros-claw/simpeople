"""Stage a fail-closed cancellation candidate; no live Native mutation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integrate_adapter(code):
    changes=[
        ("        if a:\n            current=a.get_action_task_id();name=a.get_task_name(current)",
         "        if a:\n            # Preserve the first owned stop receipt across repeated cleanup calls.\n            if self.instances[handle].get('custom_stop'):return\n            current=a.get_action_task_id();name=a.get_task_name(current)"),
        ("            if entry.get('playback_mode')=='out_and_back':\n                previous=self.instances[handle].get('custom_stop')\n                if previous and previous['retired_native_task_id']==current:return",
         "            from .custom_stop import needs_settlement\n            if needs_settlement(entry):"),
    ]
    for old,new in changes:
        if code.count(old)!=1:raise ValueError('review Native stop integration drift')
        code=code.replace(old,new)
    return code


def integrate_engine(code):
    old="        if t['status'] in TERMINAL:return self.public(t)\n        a=self.actor(t['actor_id']); a['control_epoch']+=1"
    new="        if t['status'] in TERMINAL:return self.public(t)\n        if t.get('cancel_requested'):\n            return {**self.public(t),'cancellation':'accepted'}\n        a=self.actor(t['actor_id']); a['control_epoch']+=1"
    if code.count(old)!=1:raise ValueError('review cancellation integration drift')
    return code.replace(old,new)


def prepare(base,expected,destination):
    base=Path(base).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('preserve previous candidates')
    if sha(base/'source_manifest.json')!=expected:raise ValueError('base manifest changed')
    manifest=json.loads((base/'source_manifest.json').read_text())
    for name,digest in manifest.items():
        if not (base/name).resolve().is_relative_to(base) or sha(base/name)!=digest:raise ValueError('base input changed: '+name)
    adapter=integrate_adapter((base/'src/simpeople/backends/native/adapter.py').read_text())
    engine=integrate_engine((base/'src/simpeople/core/engine.py').read_text())
    destination.mkdir(parents=True)
    for name in manifest:
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(base/name,target)
    (destination/'src/simpeople/backends/native/adapter.py').write_text(adapter)
    (destination/'src/simpeople/core/engine.py').write_text(engine)
    shutil.copy2(ROOT/'src/simpeople/backends/native/custom_stop.py',destination/'src/simpeople/backends/native/custom_stop.py')
    profile=destination/'src/simpeople/core/gesture_profiles.py'
    spec=importlib.util.spec_from_file_location('canonical_stop_profile',profile);g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
    if not {'backends/native/adapter.py','backends/native/custom_stop.py','core/engine.py'}<=set(g.IMPLEMENTATION_FILES):raise ValueError('stop code missing from domain fingerprint')
    revision=g.implementation_revision(destination/'src/simpeople')
    catalog=destination/'configs/native_gesture_catalog.json';data=json.loads(catalog.read_text())
    for record in data['records']:
        record['status']='discovered'
        for k in ['evidence_run','evidence_sha256','replay_audit_sha256']:record.pop(k,None)
        for variant in record.get('startup_profiles',{}).values():
            variant.update(status='discovered',implementation_sha256=revision,scope='New owned-stop execution code; fresh Native qualification required.')
            for k in list(variant):
                if k.endswith('_sha256') and k!='implementation_sha256' or k in ['evidence_run','legacy_regression_run']:variant.pop(k)
    catalog.write_text(json.dumps(data,indent=2)+'\n')
    frozen={n:sha(destination/n) for n in manifest}
    (destination/'source_manifest.json').write_text(json.dumps(frozen,indent=2)+'\n')
    changed=[n for n in manifest if frozen[n]!=manifest[n]]
    assert set(changed)=={'src/simpeople/backends/native/adapter.py','src/simpeople/core/engine.py','src/simpeople/backends/native/custom_stop.py','configs/native_gesture_catalog.json'}
    result={'source_manifest_sha256':sha(destination/'source_manifest.json'),'implementation_sha256':revision,'changed_files':changed,'previous_native_proof_transferred':False,'production_source_installed':False,'qualified_generated_native_rigs':[],'scope':'Canonical finite-loop stop ownership/window candidate. No SDK pose writes, budget change or fresh Native proof.'}
    (destination/'origin.json').write_text(json.dumps(result,indent=2)+'\n')
    for name,digest in manifest.items():assert sha(base/name)==digest
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--expected',required=True);p.add_argument('--destination',required=True);a=p.parse_args()
    print(json.dumps(prepare(a.base,a.expected,a.destination),indent=2))
