"""Freeze a new, unqualified diagnostic candidate; never edit a proven source."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def integrate(code):
    if 'simpeople.core.path_diagnostics' in code:raise ValueError('diagnostics already installed')
    patches=[
        ('from simpeople.core.candidate_paths import conflicts as candidate_conflicts,destination as candidate_destination,alternative as candidate_alternative,goal_leases',
         'from simpeople.core.candidate_paths import conflicts as candidate_conflicts,destination as candidate_destination,alternative as candidate_alternative,goal_leases\nfrom simpeople.core.path_diagnostics import report_search_wait,select_candidate'),
        ("        start=next((n for n in starts if n not in blocked and self.grid.can_reserve(handle,self.grid.sweep(obs['position_m'],self.grid.point(n)),self.positions,obs['position_m'],self.grid.point(n))\n                    and self.grid_connection(obs['position_m'],self.grid.point(n))),None)",
         "        start,start_checks=select_candidate(starts,blocked,\n            lambda n:self.grid.can_reserve(handle,self.grid.sweep(obs['position_m'],self.grid.point(n)),self.positions,obs['position_m'],self.grid.point(n)),\n            lambda n:self.grid_connection(obs['position_m'],self.grid.point(n)))"),
        ('        if start is None:self.block(rid,job);return',
         "        if start is None:\n            report_search_wait(self,handle,rid,job,obs,'start_candidate_unavailable',goal,starts,blocked,start_checks=start_checks)\n            self.block(rid,job);return"),
        ("        end=next((n for n in ends if n not in blocked and self.grid_connection(self.grid.point(n),goal,node_is_start=True)\n                  and (not self.runtime_policy['dynamic_edges_enabled'] or self.grid.can_reserve(handle,self.grid.sweep(self.grid.point(n),goal),self.positions,self.grid.point(n),goal))),None)",
         "        end,goal_checks=select_candidate(ends,blocked,\n            lambda n:self.grid.can_reserve(handle,self.grid.sweep(self.grid.point(n),goal),self.positions,self.grid.point(n),goal),\n            lambda n:self.grid_connection(self.grid.point(n),goal,node_is_start=True),\n            connector_first=True,clearance_required=self.runtime_policy['dynamic_edges_enabled'])"),
        ('        if not path:self.block(rid,job);return',
         "        if not path:\n            report_search_wait(self,handle,rid,job,obs,'goal_candidate_unavailable' if end is None else 'grid_path_unavailable',\n                               goal,starts,blocked,start=start,ends=ends,end=end,start_checks=start_checks,goal_checks=goal_checks)\n            self.block(rid,job);return"),
        ("        if len(path)==1 and math.dist(here[:2],self.grid.point(start)[:2])<=.35 and goal_cells & blocked:self.block(rid,job);return",
         "        if len(path)==1 and math.dist(here[:2],self.grid.point(start)[:2])<=.35 and goal_cells & blocked:\n            report_search_wait(self,handle,rid,job,obs,'goal_footprint_blocked',goal,starts,blocked,start=start,ends=ends,end=end,goal_cells=goal_cells,start_checks=start_checks,goal_checks=goal_checks)\n            self.block(rid,job);return"),
    ]
    for before,after in patches:
        if code.count(before)!=1:raise ValueError('planner integration changed; review before applying')
        code=code.replace(before,after)
    ast.parse(code);return code


def prepare(base,expected_manifest,destination):
    base=Path(base).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('preserve previous candidates; use a new destination')
    if sha(base/'source_manifest.json')!=expected_manifest:raise ValueError('base manifest differs')
    manifest=json.loads((base/'source_manifest.json').read_text());helper='src/simpeople/core/path_diagnostics.py'
    if helper in manifest:raise ValueError('base already contains path diagnostics')
    for name,digest in manifest.items():
        if not (base/name).resolve().is_relative_to(base) or sha(base/name)!=digest:raise ValueError('base bytes differ: '+name)
    destination.mkdir(parents=True)
    for name in manifest:
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(base/name,target)
    native=destination/'src/simpeople/backends/native/reservations.py';native.write_text(integrate(native.read_text()))
    shutil.copy2(ROOT/helper,destination/helper)
    profile=destination/'src/simpeople/core/gesture_profiles.py';code=profile.read_text();tree=ast.parse(code)
    assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='IMPLEMENTATION_FILES' for t in n.targets))
    files=ast.literal_eval(assignment.value)
    if len(files)!=15 or 'backends/native/arrival_recovery.py' not in files:raise ValueError('requires reviewed fifteen-file arrival-recovery base')
    lines=code.splitlines(keepends=True);profile.write_text(''.join(lines[:assignment.lineno-1])+'IMPLEMENTATION_FILES = '+repr((*files,'core/path_diagnostics.py'))+'\n'+''.join(lines[assignment.end_lineno:]))
    spec=importlib.util.spec_from_file_location('diagnostic_gesture_profile',profile);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    revision=module.implementation_revision(destination/'src/simpeople')
    catalog=destination/'configs/native_gesture_catalog.json';data=json.loads(catalog.read_text())
    for record in data['records']:
        record['status']='discovered'
        for key in ['evidence_run','evidence_sha256','replay_audit_sha256']:record.pop(key,None)
        for variant in record.get('startup_profiles',{}).values():
            variant['status']='discovered';variant['implementation_sha256']=revision
            for key in ['evidence_run','evidence_sha256','replay_audit_sha256']:variant.pop(key,None)
            variant['scope']='New diagnostic execution source; no previous Native qualification transferred.'
    catalog.write_text(json.dumps(data,indent=2)+'\n')
    frozen={name:sha(destination/name) for name in sorted([*manifest,helper])}
    (destination/'source_manifest.json').write_text(json.dumps(frozen,indent=2)+'\n')
    changed=[n for n in manifest if frozen[n]!=manifest[n]]
    assert set(changed)=={'src/simpeople/backends/native/reservations.py','src/simpeople/core/gesture_profiles.py','configs/native_gesture_catalog.json'}
    origin={'base_source':str(base),'base_manifest_sha256':expected_manifest,'source_file_count':len(frozen),
            'source_manifest_sha256':sha(destination/'source_manifest.json'),'changed_files':sorted(changed),'added_files':[helper],
            'implementation_files':list(module.IMPLEMENTATION_FILES),'implementation_sha256':revision,'builder_sha256':sha(__file__),
            'previous_native_proof_transferred':False,'production_source_installed':False,'qualified_generated_native_rigs':[],
            'scope':'New log/candidate-check execution source. CPU equivalence is not fresh Native evidence.'}
    (destination/'origin.json').write_text(json.dumps(origin,indent=2)+'\n')
    for name,digest in manifest.items():assert sha(base/name)==digest,'original source mutated'
    return origin


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-source',required=True);p.add_argument('--expected-manifest-sha256',required=True);p.add_argument('--destination',required=True);a=p.parse_args()
    print(json.dumps(prepare(a.base_source,a.expected_manifest_sha256,a.destination),indent=2))
