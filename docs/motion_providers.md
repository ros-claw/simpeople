# Motion providers and execution boundaries

The default executor is Isaac Behavior/Navigation. It owns live actor roots and
bones. A motion provider produces an asset; it is not an additional live actor
controller. Disabling a provider keeps native activities available and loads no
model dependencies into Isaac's Python environment.

| Path | Current implementation | Evidence boundary |
| --- | --- | --- |
| Native activities | Move/Jog, seat lifecycle, queue/resource supervision and qualified local clips | Query exact-asset capabilities and actual task outcomes. Historical 10/30/50 scene results do not qualify every new workload. |
| Native head/hand control | Verified domains in the capability catalog; default hold limit remains 0.6 s | Longer owned-base experiments are separate; reach is not grasp or contact force. |
| MotionBricks v0.2 | Separate pinned worker, official SOMA FP32 model, prepare/status/cancel, raw/decoded/corrected arrays | Same-SOMA generation and worker isolation verified. Generated is not native execution. |
| Native pose context | Read-only actual four-frame ring, instance/epoch/task fencing, actual skeleton calibration | Functional probe and immediate cancellation invalidation verified. Female direct SDK roundtrip still fails on a thigh-twist bone. |
| Generated native clips | Startup preload/import and actual playback probes | Human body mapping and lifecycle have passed scoped tests; world seams, sole support and some finite termination remain failed. Qualified generated rigs stay empty. |
| Runtime publication | Independent actual SDK probe | `preload_only`: live reload and native continuous queue unverified/failed. Online application remains disabled. |
| Kimodo / ARDY | Future provider candidates | No installed or qualified provider claim; no automatic dependency or license assumption. |

`people_motion` is an optional MCP operation. Without
`SIMPEOPLE_MOTION_ENDPOINT`, it returns `ACTION_UNSUPPORTED` and leaves native
tasks unchanged. Configuring a local worker permits `prepare`, `status`, and
`cancel`; none publishes an action to a live actor. Keep the returned worker
instance ID on subsequent requests. Stale worker or task identities are rejected.
Never fabricate executed context to satisfy a MotionSpec.

The reusable pose bridge retains full SOMA context and separate lossy reference
projection diagnostics. It samples actual native SDK joints after an executed
step and clears history on task, instance, binding revision, gap or cancellation.
It is currently wired into explicit probes, not a default live generation loop.
Calibration clones static skeleton attributes without cloning live Behavior
ownership. Authored goals and return holds are labeled as authored inputs, not
observed history. See [the latest native context report](../reports/ITERATION_20261113_POSE_CONTEXT.md).

Inspect `configs/motion_capabilities.json` for the conservative measured
classification. The absence of a qualified generated rig is intentional: do not
advertise arbitrary online native animation, streaming, or 50 generated people.
T7 native scale tests follow a qualified single-person path. Model batching speed
cannot establish Isaac navigation/rendering throughput or body quality.

The worker setup and protocol are described in [motionbricks_worker.md](motionbricks_worker.md).
Agent integration and refusal handling are in [plugins.md](plugins.md).
