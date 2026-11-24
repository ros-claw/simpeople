"""Conditional gesture domains, without Kit or writable runtime access."""
import hashlib
import math
from pathlib import Path

IMPLEMENTATION_FILES = ('backends/native/gestures.py', 'backends/native/adapter.py', 'backends/native/idle_profile.py', 'core/gesture_profiles.py', 'core/gestures.py', 'core/engine.py', 'core/protocol.py', 'core/quality_catalog.py', 'core/facing_runtime.py', 'backends/native/custom_stop.py', 'backends/native/reservations.py', 'core/gesture_runtime.py', 'core/action_space.py', 'core/interaction_management.py', 'backends/native/arrival_recovery.py')


def implementation_revision(package_root):
    digest = hashlib.sha256()
    for name in IMPLEMENTATION_FILES:
        digest.update(name.encode() + b'\0')
        digest.update(hashlib.sha256((Path(package_root) / name).read_bytes()).digest())
    return digest.hexdigest()


def select_profile(record, startup, effective, implementation_sha256, allow_discovered=False):
    """Extend only an exact asset/runtime record under the audited startup mode.

    Missing, stale or changed conditions retain the original short domain.
    A discovered extension is available only to explicitly unverified probes.
    """
    result = dict(record)
    if not record.get('revision_match') or record.get('status') not in {'verified', 'discovered'}:
        return result
    if not startup or startup.get('mode') != 'basic' or startup.get('active_tags') != ['Idle']:
        return result
    variant = record.get('startup_profiles', {}).get('basic')
    if not variant:
        return result
    response = effective.get('response_time_s')
    jitter = effective.get('response_random_offset_s')
    matched = (effective.get('idle_tags') == ['Idle']
               and isinstance(response, (int, float)) and not isinstance(response, bool)
               and math.isfinite(response) and abs(response - 1 / 30) < 1e-8
               and isinstance(jitter, (int, float)) and not isinstance(jitter, bool)
               and math.isfinite(jitter) and jitter == 0)
    if not matched or variant.get('implementation_sha256') != implementation_sha256:
        return result
    status = variant.get('status')
    if status != 'verified' and not (allow_discovered and status == 'discovered'):
        return result
    duration = variant.get('max_hold_duration_s')
    if (not isinstance(duration, (int, float)) or isinstance(duration, bool)
            or not math.isfinite(duration) or not record.get('max_hold_duration_s', 0) <= duration <= 2):
        return result
    if status == 'verified' and not all(variant.get(k) for k in ('evidence_run', 'evidence_sha256', 'replay_audit_sha256')):
        return result
    result.update(status=status, max_hold_duration_s=duration,
                  selected_startup_profile='basic_fixed30_v1',
                  startup_profile_evidence=dict(variant))
    if variant.get('scope'):
        result['scope'] = variant['scope']
    return result
