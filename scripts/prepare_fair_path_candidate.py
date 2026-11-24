"""Stage guarded path search and correct planner wait clocks, without adoption."""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import shutil

from prepare_integrated_runtime_candidate import check_manifest, clear_proof, sha

ROOT = Path(__file__).resolve().parents[1]


def integrate_reservations(code):
    changes = [
        ("    def block(self,rid,job):\n",
         "    def block(self,rid,job):\n"
         "        # Planner failure before admission must accrue actual waiting time.\n"
         "        if rid in self.fair_gate.pending:self.fair_gate.waiting(rid,self.now)\n"),
        ("        blocked=self.grid.blocked(handle,self.positions)\n",
         "        blocked=self.grid.blocked(handle,self.positions)\n"
         "        edges=ClearanceEdges(self.grid,handle,self.positions) if self.runtime_policy['dynamic_edges_enabled'] else None\n"
         "        fair_edges=None\n"
         "        if self.runtime_policy.get('fair_path_edges_enabled',False) and self.runtime_policy['traffic_fairness_enabled']:\n"
         "            from simpeople.core.fair_edges import FairEdges\n"
         "            edges=fair_edges=FairEdges(self.grid,edges if edges is not None else self.grid.edges,\n"
         "                self.fair_gate,rid,self.grid.footprint(goal))\n"),
        ("            lambda n:self.grid.can_reserve(handle,self.grid.sweep(obs['position_m'],self.grid.point(n)),self.positions,obs['position_m'],self.grid.point(n)),\n",
         "            lambda n:self.grid.can_reserve(handle,self.grid.sweep(obs['position_m'],self.grid.point(n)),self.positions,obs['position_m'],self.grid.point(n)) and (fair_edges is None or fair_edges.allows(obs['position_m'],self.grid.point(n))),\n"),
        ("            lambda n:self.grid.can_reserve(handle,self.grid.sweep(self.grid.point(n),goal),self.positions,self.grid.point(n),goal),\n",
         "            lambda n:self.grid.can_reserve(handle,self.grid.sweep(self.grid.point(n),goal),self.positions,self.grid.point(n),goal) and (fair_edges is None or fair_edges.allows(self.grid.point(n),goal)),\n"),
        ("            connector_first=True,clearance_required=self.runtime_policy['dynamic_edges_enabled'])\n"
         "        edges=ClearanceEdges(self.grid,handle,self.positions) if self.runtime_policy['dynamic_edges_enabled'] else None\n",
         "            connector_first=True,clearance_required=self.runtime_policy['dynamic_edges_enabled'] or fair_edges is not None)\n"),
    ]
    if 'fair_path_edges_enabled' in code or 'if rid in self.fair_gate.pending:self.fair_gate.waiting' in code:
        raise ValueError('candidate already includes these hooks')
    for old, new in changes:
        if code.count(old) != 1:
            raise ValueError('review guarded-path integration drift')
        code = code.replace(old, new)
    ast.parse(code)
    return code


def integrate_policy(code):
    tree = ast.parse(code)
    node = next(n for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'DEFAULT_POLICY' for t in n.targets))
    values = ast.literal_eval(node.value)
    if 'fair_path_edges_enabled' in values:
        raise ValueError('candidate policy already includes guarded paths')
    values['fair_path_edges_enabled'] = False
    lines = code.splitlines(keepends=True)
    code = ''.join(lines[:node.lineno-1])+'DEFAULT_POLICY = '+repr(values)+'\n'+''.join(lines[node.end_lineno:])
    before = "    if not isinstance(value['dynamic_edges_enabled'],bool):raise ValueError('invalid dynamic edge flag')"
    if code.count(before) != 1:
        raise ValueError('review guarded-path policy validation drift')
    return code.replace(before, "    if not isinstance(value['fair_path_edges_enabled'],bool):raise ValueError('invalid fair path edge flag')\n"+before)


def prepare(base, expected, destination):
    base = Path(base).resolve(); destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(base):
        raise ValueError('new separate candidate directory required')
    manifest = check_manifest(base, base/'source_manifest.json', expected)
    adapter_name = 'src/simpeople/backends/native/reservations.py'
    policy_name = 'src/simpeople/core/runtime_policy.py'
    adapter = integrate_reservations((base/adapter_name).read_text())
    policy = integrate_policy((base/policy_name).read_text())
    destination.mkdir(parents=True)
    for name in manifest:
        target = destination/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base/name, target)
    (destination/adapter_name).write_text(adapter); (destination/policy_name).write_text(policy)
    helper = 'src/simpeople/core/fair_edges.py'
    shutil.copy2(ROOT/helper, destination/helper)
    inputs = set(manifest) | {helper}; package = 'src/simpeople/'
    implementation = tuple(sorted(n[len(package):] for n in inputs
                                  if n.startswith(package) and n.endswith(('.py', '.cpp'))))
    profile = destination/package/'core/gesture_profiles.py'; code = profile.read_text()
    node = next(n for n in ast.parse(code).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'IMPLEMENTATION_FILES' for t in n.targets))
    lines = code.splitlines(keepends=True)
    profile.write_text(''.join(lines[:node.lineno-1])+'IMPLEMENTATION_FILES = '+repr(implementation)+'\n'+''.join(lines[node.end_lineno:]))
    spec = importlib.util.spec_from_file_location('fair_path_profile', profile)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    revision = module.implementation_revision(destination/package)
    catalog_path = destination/'configs/native_gesture_catalog.json'; catalog = json.loads(catalog_path.read_text())
    for record in catalog['records']:
        for row in [record, *record.get('startup_profiles', {}).values()]:
            clear_proof(row)
            if 'implementation_sha256' in row: row['implementation_sha256'] = revision
            row['scope'] = 'New guarded path/wait clock candidate; fresh Native proof required.'
    catalog_path.write_text(json.dumps(catalog, indent=2)+'\n')
    frozen = {n: sha(destination/n) for n in sorted(inputs)}
    (destination/'source_manifest.json').write_text(json.dumps(frozen, indent=2)+'\n')
    changes = [n for n in frozen if frozen[n] != manifest.get(n)]
    assert set(changes) == {adapter_name, policy_name, helper, 'src/simpeople/core/gesture_profiles.py',
                            'configs/native_gesture_catalog.json'}
    check_manifest(base, base/'source_manifest.json', expected)
    result = {'source_manifest_sha256': sha(destination/'source_manifest.json'),
              'parent_manifest_sha256': expected, 'changes': changes,
              'source_files': len(frozen), 'execution_code_files': len(implementation),
              'implementation_sha256': revision, 'production_source_installed': False,
              'previous_proof_transferred': False, 'native_verified': False,
              'scope': 'Search avoids older fences; final clearance/admission/escape verification unchanged. Existing blocked ticket clock fixed, no claims/priorities/goals/deadlines waived.'}
    (destination/'origin.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ['base', 'expected', 'destination']: p.add_argument('--'+name, required=True)
    a = p.parse_args(); print(json.dumps(prepare(a.base, a.expected, a.destination), indent=2))
