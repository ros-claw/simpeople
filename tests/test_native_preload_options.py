"""Startup selection must preserve proofs and reject incompatible domains."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SPEC = importlib.util.spec_from_file_location('native_preload_options',
    Path(__file__).resolve().parents[1] / 'scripts/native_preload_options.py')
OPTIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OPTIONS)
DOMAIN = dict(schema_version='simpeople.native-motion-startup.v1', idle_tags=['Idle'],
              response_time_s=1 / 30, response_random_offset_s=0,
              nav_blocked_timeout_s=3, api_seed=42)


def bundle(tmp_path):
    source = tmp_path / 'bundle'; source.mkdir()
    registry = dict(schema_version='simpeople.custom_actions.v1', registration_source='fixed_cache_uris',
                    actions={'reach': dict(clip='cache://motion/reach.usda', skeleton='cache://motion/rig.usda',
                                          canonical_entry=dict(native_startup_conditions=copy.deepcopy(DOMAIN)))})
    # An empty certificate is valid input, but grants no runtime qualification.
    (source / 'actions.json').write_text(json.dumps(registry))
    (source / 'acceptance.json').write_text('{}\n')
    config = tmp_path / 'configs'; config.mkdir()
    for name in ['custom_actions.json', 'custom_action_acceptance.json']:
        (config / name).write_text('original snapshot bytes')
    return source, config, registry


def test_default_does_not_select_profile_or_touch_snapshot(tmp_path):
    assert OPTIONS.stage_generated_preload(None, tmp_path / 'absent',
        custom_actions=False, idle_profile='default', seed=42) is None
    assert not (tmp_path / 'absent').exists()


def test_exact_inputs_preserved_without_minting_or_expanding_acceptance(tmp_path):
    source, config, _ = bundle(tmp_path)
    receipt = OPTIONS.stage_generated_preload(source, config,
        custom_actions=True, idle_profile='basic', seed=42)
    for original, staged in [('actions.json', 'custom_actions.json'),
                             ('acceptance.json', 'custom_action_acceptance.json')]:
        assert (config / staged).read_bytes() == (source / original).read_bytes()
        assert receipt['input_sha256'][original] == hashlib.sha256((source / original).read_bytes()).hexdigest()
    assert json.loads((config / 'custom_action_acceptance.json').read_text()) == {}
    assert receipt['execution_runtime_flags'] == {'cooperative_finite_stop': True}


@pytest.mark.parametrize('bad', ['no_optin', 'default_idle', 'seed', 'bool_seed', 'uri',
                                'missing_domain', 'idle_tags', 'response', 'registry', 'acceptance'])
def test_incompatible_bundle_is_rejected_before_snapshot_changes(tmp_path, bad):
    source, config, registry = bundle(tmp_path)
    kwargs = dict(custom_actions=True, idle_profile='basic', seed=42)
    entry = registry['actions']['reach']
    if bad == 'no_optin': kwargs['custom_actions'] = False
    elif bad == 'default_idle': kwargs['idle_profile'] = 'default'
    elif bad == 'seed': kwargs['seed'] = 43
    elif bad == 'bool_seed': kwargs['seed'] = True
    elif bad == 'uri': entry['clip'] = '/tmp/unbound.usda'
    elif bad == 'missing_domain': entry['canonical_entry'].pop('native_startup_conditions')
    elif bad == 'idle_tags': entry['canonical_entry']['native_startup_conditions']['idle_tags'] = ['Idle', 'IdleGroove']
    elif bad == 'response': entry['canonical_entry']['native_startup_conditions']['response_time_s'] = .3
    elif bad == 'registry': registry['actions'] = []
    else: (source / 'acceptance.json').write_text('[]')
    (source / 'actions.json').write_text(json.dumps(registry))
    with pytest.raises(ValueError):
        OPTIONS.stage_generated_preload(source, config, **kwargs)
    assert all(p.read_text() == 'original snapshot bytes' for p in config.iterdir())


def test_real_entrypoint_imports_snapshot_before_package_is_pinned(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name in ['scripts/kit_main.py', 'scripts/native_preload_options.py',
                 'src/simpeople/__init__.py', 'src/simpeople/core/modes.py',
                 'src/simpeople/motion/startup.py',
                 'src/simpeople/backends/native/linear_sweep_cpu.cpp']:
        target = tmp_path / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)
    (tmp_path / 'reports').mkdir()
    (tmp_path / 'reports/capability_matrix.json').write_text('{}')
    # Execute the actual entrypoint in a fresh interpreter up to the SDK import;
    # no fake Native backend, world or playback result is supplied.
    code = '''import importlib.abc,json,runpy,sys
class StopBeforeSDK(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname == 'isaacsim': raise ModuleNotFoundError('test stops before SDK')
sys.meta_path.insert(0,StopBeforeSDK())
sys.argv=[sys.argv[1],'--run-id','bootstrap-source-check']
try: runpy.run_path(sys.argv[0],run_name='__main__')
except ModuleNotFoundError as error:
 assert str(error)=='test stops before SDK'
 print(json.dumps({name:sys.modules[name].__file__ for name in
                  ['simpeople','simpeople.core.modes','simpeople.motion.startup']}))
else: raise AssertionError('SDK boundary was not reached')
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'scripts/kit_main.py')],
                            text=True, capture_output=True, check=True)
    modules = json.loads(result.stdout)
    snapshot = tmp_path / 'runs/bootstrap-source-check/source_snapshot'
    assert all(Path(path).is_relative_to(snapshot / 'src') for path in modules.values())
    cpp = 'src/simpeople/backends/native/linear_sweep_cpu.cpp'
    assert (snapshot / cpp).read_bytes() == (root / cpp).read_bytes()
    manifest = json.loads((snapshot.parent / 'manifest.json').read_text())
    assert manifest['source_sha256'][cpp] == hashlib.sha256((root / cpp).read_bytes()).hexdigest()
