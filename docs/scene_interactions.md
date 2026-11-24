# Scene interactions

`people_list_interactions` (CLI `list_interactions`) reads explicitly declared
`seat`, `queue`, `workstation` and `activity_bay` targets. Filter by `kind` or
`target`, and paginate with `offset`/`limit`. Objects without a declared kind or
matching local overlay do not acquire interaction actions automatically.

Each target includes its USD path, public Z-up metre position/bounds, approach
and exit points, hips/palm anchors when declared, allowed actions, capacity,
release condition, geometry revision and evidence status. Live occupants,
waiters and cleanup are separate from geometry. Actor movement and queue
admission do not invalidate a static target revision.

The native adapter reads current USD geometry and marker transforms on the Kit
main thread. `configs/interaction_targets.json` supplies explicit workstation
annotations for the existing scene; declared semantics take precedence over
an overlay naming the same physical prim. The registry rejects duplicate physical
resource aliases. It does not infer seats or reach targets from RGB.

## Planning and execution

Read session/episode scope, query the target, then call
`people_validate_interaction` with actor, action, target and geometry revision.
Move to a returned `approach_points_m` location. Bind the actual interaction
step to that revision and validate the complete activity before submitting.

For a workstation wait, substitute the queried ID and digest:

```json
{
  "action": "wait",
  "duration_s": 2,
  "resource_id": "work_00",
  "interaction_revision": "SHA256_FROM_TARGET_QUERY"
}
```

For `sit`/`queue`, the target semantic ID identifies the resource. A bound
`custom_action` needs the bay's `resource_id` and registered clip as `target`.
Only sit, queue and explicit wait/custom-action resources accept this field.
The runtime checks it at submission and during each bound step. A changed
transform, mesh, anchor or definition produces `TARGET_STALE`; it does not
silently retarget the old instruction. Unbound legacy activities retain their
existing behavior. Query and validate a fresh revision before a new attempt.

Preflight returns `advisory=true`, `reservation_acquired=false` and
`execution_completed=false`. It checks installed action capabilities, live
admission, static NavMesh reachability and current managed-body clearance at
approach/exit points. A free logical lease does not hide a body still standing at
the approach. These body checks use the existing 0.9 m root-distance proxy;
unavailable poses remain explicit. `at_approach` is a horizontal-distance
proxy, not a completed interaction or future corridor reservation. A full queue
can report bounded outside waiting; a capacity rejection remains explicit.

## Evidence boundaries

Geometry discovery, a configured chair profile, native action support and
actor-specific fit evidence are separate. Generic targets remain `discovered`
until revision-bound evidence is supplied. Seat preflight additionally exposes
the existing asset/motion/chair quality record. Discovery-mode acceptance cannot
promote an unverified clip. A missing palm anchor does not become a reach target.
Current `look_at` uses the legacy whole-body-facing action. Separate `head_look`
and `reach_hand` have limited exact-revision native qualification; see
[native gestures](native_gestures.md) for the two accepted assets, sampled
standing domain, 0.6 s hold limit and measured return. Workstations need explicit
allowed actions and look/selected-palm anchors. Existing default workstation
actions remain unchanged. Palm-labelled coordinates are SDK wrist targets and
do not certify skin contact.

`examples/interaction_room_handoff.json` and
`scripts/probe_interactions_native.py --layout room` exercise a small room with
explicit handoff semantics. This fixture consumes the handoff's `locations`;
the existing extension's `semantics_file` also accepts that locations mapping.
The probe changes its own workstation geometry,
checks stale-plan rejection and fresh execution, and keeps a witness actor moving.
`scripts/probe_interactions_mcp.py` checks the real read-only stdio MCP path.
