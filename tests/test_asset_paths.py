from pathlib import Path
import pytest
from simpeople.core.asset_paths import resolve_asset_path

def test_portable_registry_and_external_root(monkeypatch,tmp_path):
    monkeypatch.delenv('SIMPEOPLE_CHARACTER_DIR',raising=False)
    assert resolve_asset_path('characters://person/person.usd',tmp_path)==str(tmp_path/'assets/characters/person/person.usd')
    monkeypatch.setenv('SIMPEOPLE_CHARACTER_DIR','/shared/people')
    assert resolve_asset_path('characters://person/person.usd',tmp_path)=='/shared/people/person/person.usd'
    assert resolve_asset_path('cache://behavior/lib.usd',tmp_path)==str(tmp_path/'assets/cache/behavior/lib.usd')
    with pytest.raises(ValueError):resolve_asset_path('characters://../secret',tmp_path)
    with pytest.raises(ValueError):resolve_asset_path('cache:///etc/passwd',tmp_path)
