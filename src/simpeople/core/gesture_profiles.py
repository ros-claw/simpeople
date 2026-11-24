"""Conditional gesture domains, without Kit or writable runtime access."""
import hashlib
import math
from pathlib import Path

IMPLEMENTATION_FILES = ('__init__.py', 'backends/native/adapter.py', 'backends/native/arrival_recovery.py', 'backends/native/body_geometry.py', 'backends/native/canonical_recovery_stop.py', 'backends/native/cooperative_finite_stop.py', 'backends/native/custom_actions.py', 'backends/native/custom_stop.py', 'backends/native/deadweight_cinema.py', 'backends/native/deadweight_director.py', 'backends/native/deadweight_set.py', 'backends/native/deadweight_v2_actor.py', 'backends/native/deadweight_v2_director.py', 'backends/native/deadweight_v2_qa.py', 'backends/native/deadweight_v2_set.py', 'backends/native/deferred_custom_stop.py', 'backends/native/environments.py', 'backends/native/foot_geometry.py', 'backends/native/gestures.py', 'backends/native/idle_profile.py', 'backends/native/interactions.py', 'backends/native/linear_sweep.py', 'backends/native/linear_sweep_cpu.cpp', 'backends/native/local_pose.py', 'backends/native/local_yield.py', 'backends/native/local_yield_stop.py', 'backends/native/mesh_intersections.py', 'backends/native/motion_features.py', 'backends/native/motion_import.py', 'backends/native/overlay.py', 'backends/native/performance_score.py', 'backends/native/phase_end_stop.py', 'backends/native/phase_import.py', 'backends/native/platform04_90_animation.py', 'backends/native/platform04_90_director.py', 'backends/native/platform04_90_observation.py', 'backends/native/platform04_90_scene.py', 'backends/native/platform04_animation.py', 'backends/native/platform04_director.py', 'backends/native/platform04_feature_director.py', 'backends/native/platform04_feature_score.py', 'backends/native/platform04_r2_bottle.py', 'backends/native/platform04_r2_director.py', 'backends/native/platform04_r2_motion.py', 'backends/native/platform04_scene.py', 'backends/native/pose_bridge.py', 'backends/native/probe_scenes.py', 'backends/native/production.py', 'backends/native/production_art.py', 'backends/native/recording.py', 'backends/native/reservations.py', 'backends/native/scene.py', 'backends/native/seat_geometry.py', 'backends/native/sole_floor.py', 'backends/native/stationary_detour.py', 'core/action_space.py', 'core/admission.py', 'core/asset_paths.py', 'core/body_buckets.py', 'core/candidate_paths.py', 'core/cinema.py', 'core/cleanup_state.py', 'core/clip_quality.py', 'core/command_benchmark.py', 'core/custom_action_phases.py', 'core/deadweight.py', 'core/drainage_candidate.py', 'core/engine.py', 'core/errors.py', 'core/events.py', 'core/facing_runtime.py', 'core/fair_edges.py', 'core/funicular.py', 'core/gesture_profiles.py', 'core/gesture_runtime.py', 'core/gestures.py', 'core/interaction_management.py', 'core/journal.py', 'core/management.py', 'core/modes.py', 'core/monitor.py', 'core/passage_prefix.py', 'core/path_diagnostics.py', 'core/population.py', 'core/protocol.py', 'core/pursuit.py', 'core/quality.py', 'core/quality_catalog.py', 'core/queue_runtime.py', 'core/release_scene.py', 'core/resources.py', 'core/route_history.py', 'core/runtime_policy.py', 'core/scene_semantics.py', 'core/seat_egress.py', 'core/seats.py', 'core/stationary_blockers.py', 'core/tail_release.py', 'core/traffic.py', 'core/wait_snapshot.py', 'core/workloads.py', 'motion/__init__.py', 'motion/admission_window.py', 'motion/compose.py', 'motion/contracts.py', 'motion/entry.py', 'motion/executed_quality.py', 'motion/goals.py', 'motion/jobs.py', 'motion/pose_bridge.py', 'motion/providers/__init__.py', 'motion/providers/base.py', 'motion/providers/motionbricks.py', 'motion/quality.py', 'motion/recovery_quality.py', 'motion/retarget_chain.py', 'motion/retime.py', 'motion/return_observer.py', 'motion/rig.py', 'motion/startup.py', 'motion/validation.py', 'tools/bridge.py', 'tools/claude_benchmark.py', 'tools/cli.py', 'tools/client.py', 'tools/doctor.py', 'tools/launch.py', 'tools/mcp_server.py', 'tools/motion.py', 'tools/runtime_contract.py')


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
    # The selected domain must name its own execution evidence. Keeping the
    # base record's provenance here would attribute a two-second hold to a
    # different startup mode or an older, shorter calibration run.
    for key in ('evidence_run', 'evidence_sha256', 'replay_audit_sha256'):
        result.pop(key, None)
        if key in variant:
            result[key] = variant[key]
    if variant.get('scope'):
        result['scope'] = variant['scope']
    return result
