import pytest
from simpeople.core.modes import resolve_mode

def test_modes_preserve_explicit_resolution_and_audit_intent():
    assert resolve_mode('interactive')['width']==1280
    assert resolve_mode('generation')['width']==1920
    assert resolve_mode('audit')['quality_audit']
    assert resolve_mode('interactive',1920,1080)['width']==1920
    assert resolve_mode('experimental',quality_audit=True)['quality_audit']
    with pytest.raises(ValueError):resolve_mode('interactive',1919,1080)
