"""Every current execution dependency must invalidate conditional qualification."""
import shutil
from pathlib import Path

import pytest

import simpeople.core.gesture_profiles as gesture_profiles
from simpeople.core.gesture_profiles import IMPLEMENTATION_FILES, implementation_revision, select_profile

ROOT = Path(gesture_profiles.__file__).resolve().parents[1]


def test_inventory_names_every_current_python_and_native_accelerator_source():
    actual = {str(p.relative_to(ROOT)) for p in ROOT.rglob('*')
              if p.is_file() and p.suffix in {'.py', '.cpp'} and '__pycache__' not in p.parts}
    assert set(IMPLEMENTATION_FILES) == actual
    assert len(IMPLEMENTATION_FILES) == len(actual)


@pytest.fixture(scope='module')
def candidate(tmp_path_factory):
    destination = tmp_path_factory.mktemp('execution_inventory')
    for name in IMPLEMENTATION_FILES:
        path = destination/name; path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, path)
    return destination, implementation_revision(destination)


@pytest.mark.parametrize('name', IMPLEMENTATION_FILES)
def test_each_changed_execution_file_rejects_the_previously_verified_profile(candidate, name):
    folder, original_revision = candidate; path = folder/name; original = path.read_bytes()
    record = dict(revision_match=True, status='verified', max_hold_duration_s=.6,
                  startup_profiles={'basic': dict(status='verified', max_hold_duration_s=2.,
                      implementation_sha256=original_revision, evidence_run='synthetic',
                      evidence_sha256='synthetic', replay_audit_sha256='synthetic')})
    startup = dict(mode='basic', active_tags=['Idle'])
    effective = dict(idle_tags=['Idle'], response_time_s=1/30, response_random_offset_s=0.)
    assert select_profile(record, startup, effective, original_revision)['max_hold_duration_s'] == 2.
    try:
        path.write_bytes(original+b'\n// changed' if path.suffix == '.cpp' else original+b'\n# changed')
        changed = implementation_revision(folder)
        assert changed != original_revision
        assert select_profile(record, startup, effective, changed)['max_hold_duration_s'] == .6
    finally:
        path.write_bytes(original)
