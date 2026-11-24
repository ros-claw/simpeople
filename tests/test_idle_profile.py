import pytest

from simpeople.backends.native.idle_profile import IDLE_TAGS_SETTING, configure_idle_profile


class Settings:
    def __init__(self, tags, accept=True):
        self.tags = tags
        self.accept = accept
        self.writes = []

    def get(self, key):
        assert key == IDLE_TAGS_SETTING
        return self.tags

    def set(self, key, value):
        assert key == IDLE_TAGS_SETTING
        self.writes.append(list(value))
        if self.accept:
            self.tags = list(value)


def test_default_observes_installed_menu_without_overwriting_it():
    settings = Settings(['Idle', 'IdleTired', 'SiteSpecificIdle'])
    receipt = configure_idle_profile(settings, 'default')
    assert settings.writes == []
    assert receipt['active_tags'] == receipt['original_tags'] == settings.tags
    settings.tags.append('LaterChange')
    assert receipt['active_tags'] == ['Idle', 'IdleTired', 'SiteSpecificIdle']


def test_basic_requires_actual_readback_and_records_previous_menu():
    settings = Settings(('Idle', 'IdleCautious'))
    receipt = configure_idle_profile(settings, 'basic')
    assert settings.writes == [['Idle']]
    assert receipt['active_tags'] == ['Idle']
    assert receipt['original_tags'] == ['Idle', 'IdleCautious']


def test_failed_sdk_setting_write_aborts_instead_of_claiming_basic():
    settings = Settings(['Idle', 'IdleTired'], accept=False)
    with pytest.raises(RuntimeError, match='readback'):
        configure_idle_profile(settings, 'basic')


@pytest.mark.parametrize('menu', [None, [], 'Idle', ['Idle', 3]])
def test_missing_or_malformed_sdk_menu_aborts_before_writing(menu):
    settings = Settings(menu)
    with pytest.raises(RuntimeError, match='unavailable'):
        configure_idle_profile(settings, 'basic')
    assert settings.writes == []


def test_unknown_profile_cannot_disable_native_idle():
    settings = Settings(['Idle'])
    with pytest.raises(ValueError):
        configure_idle_profile(settings, 'disabled')
    assert settings.writes == []
