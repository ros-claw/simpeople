import copy

import pytest

from simpeople.core.gesture_profiles import select_profile


def fixture(status='verified'):
    variant = {'status': status, 'max_hold_duration_s': 2, 'implementation_sha256': 'code-a',
               'evidence_run': 'closed-native', 'evidence_sha256': 'evidence', 'replay_audit_sha256': 'replay'}
    record = {'status': 'verified', 'revision_match': True, 'max_hold_duration_s': .6,
              'domain': {'max_yaw_deg': 45}, 'head_local_forward': [0, 0, 1],
              'startup_profiles': {'basic': variant}}
    return record, {'mode': 'basic', 'active_tags': ['Idle']}, {
        'idle_tags': ['Idle'], 'response_time_s': 1 / 30, 'response_random_offset_s': 0}


def test_verified_extension_requires_startup_and_effective_settings_and_code_revision():
    record, startup, effective = fixture()
    original = copy.deepcopy(record)
    result = select_profile(record, startup, effective, 'code-a')
    assert result['status'] == 'verified' and result['max_hold_duration_s'] == 2
    assert result['domain'] == record['domain'] and result['head_local_forward'] == [0, 0, 1]
    assert result['selected_startup_profile'] == 'basic_fixed30_v1'
    assert record == original


def test_selected_domain_reports_its_own_proof_without_mutating_base_provenance():
    record, startup, effective = fixture()
    record.update(evidence_run='old-short-run', evidence_sha256='old-evidence',
                  replay_audit_sha256='old-replay')
    original = copy.deepcopy(record)
    result = select_profile(record, startup, effective, 'code-a')
    for key in ('evidence_run', 'evidence_sha256', 'replay_audit_sha256'):
        assert result[key] == record['startup_profiles']['basic'][key]
        assert result[key] != record[key]
    assert record == original


def test_unverified_selected_domain_cannot_borrow_the_short_domain_proof():
    record, startup, effective = fixture('discovered')
    keys = ('evidence_run', 'evidence_sha256', 'replay_audit_sha256')
    record.update({key: 'short-domain-only' for key in keys})
    for key in keys:
        del record['startup_profiles']['basic'][key]
    result = select_profile(record, startup, effective, 'code-a', allow_discovered=True)
    assert result['status'] == 'discovered'
    assert not any(key in result for key in keys)
    assert all(key in record for key in keys)


@pytest.mark.parametrize('startup', [None, {}, {'mode': 'default'}, {'mode': 'basic', 'active_tags': ['Idle', 'IdleTired']}])
def test_an_existing_stage_or_unchosen_startup_never_gets_the_extension(startup):
    record, _, effective = fixture()
    assert select_profile(record, startup, effective, 'code-a')['max_hold_duration_s'] == .6


@pytest.mark.parametrize('field,value', [('idle_tags', ['Idle', 'IdleTired']), ('idle_tags', None),
                                      ('response_time_s', .3), ('response_time_s', float('nan')),
                                      ('response_time_s', True), ('response_random_offset_s', .1),
                                      ('response_random_offset_s', False)])
def test_changed_effective_settings_do_not_inherit_the_long_domain(field, value):
    record, startup, effective = fixture()
    effective[field] = value
    assert select_profile(record, startup, effective, 'code-a')['max_hold_duration_s'] == .6


def test_discovered_extension_is_only_visible_to_explicit_unverified_execution():
    record, startup, effective = fixture('discovered')
    assert select_profile(record, startup, effective, 'code-a')['max_hold_duration_s'] == .6
    result = select_profile(record, startup, effective, 'code-a', allow_discovered=True)
    assert result['status'] == 'discovered' and result['max_hold_duration_s'] == 2


def test_changed_source_or_unmatched_asset_keeps_original_domain():
    record, startup, effective = fixture()
    assert select_profile(record, startup, effective, 'different-code')['max_hold_duration_s'] == .6
    record['revision_match'] = False
    assert select_profile(record, startup, effective, 'code-a', True)['max_hold_duration_s'] == .6


@pytest.mark.parametrize('field', ['evidence_run', 'evidence_sha256', 'replay_audit_sha256'])
def test_verified_extension_cannot_omit_closed_native_proof_fields(field):
    record, startup, effective = fixture()
    del record['startup_profiles']['basic'][field]
    assert select_profile(record, startup, effective, 'code-a')['max_hold_duration_s'] == .6


@pytest.mark.parametrize('duration', [3, True, float('inf'), -.1])
def test_extension_cannot_exceed_implemented_two_second_domain(duration):
    record, startup, effective = fixture()
    record['startup_profiles']['basic']['max_hold_duration_s'] = duration
    assert select_profile(record, startup, effective, 'code-a')['max_hold_duration_s'] == .6
