"""Explicit process-start Idle selection; no Kit import or live pose writes."""

IDLE_TAGS_SETTING = '/exts/omni.anim.behavior.core/idleAnimationTags'


def configure_idle_profile(settings, profile):
    """Call on Kit's main thread, after extension load and before agents/Play.

    ``default`` observes the installed SDK menu without changing it. ``basic``
    selects only Idle for a dedicated runtime, preserving Behavior ownership.
    Neither mode certifies stationary roots, contact, or gesture duration.
    """
    if profile not in {'default', 'basic'}:
        raise ValueError('Idle profile must be default or basic')
    original = settings.get(IDLE_TAGS_SETTING)
    if not isinstance(original, (list, tuple)) or not original or any(not isinstance(tag, str) for tag in original):
        raise RuntimeError('Native Idle menu is unavailable; load Behavior before configuring it')
    original = list(original)
    if profile == 'basic':
        settings.set(IDLE_TAGS_SETTING, ['Idle'])
    active = settings.get(IDLE_TAGS_SETTING)
    expected = ['Idle'] if profile == 'basic' else original
    if not isinstance(active, (list, tuple)) or list(active) != expected:
        raise RuntimeError('Native Idle profile readback does not match the requested menu')
    return {'mode': profile, 'original_tags': original, 'active_tags': list(active),
            'setting': IDLE_TAGS_SETTING,
            'scope': 'Process-start SDK menu, before agents and Play; no per-actor pose control or stationary-root guarantee.'}
