# Request lifetime and completion

All writes still go through the main-thread Engine. Behavior / Navigation owns
the native root and skeleton. A request receipt is not a completed activity.

`list_actions` returns both actor capabilities and an `activity_contract`.
Capability labels `walk` / `run` describe gaits; a plan uses
`{"action":"move_to","target":[x,y,z],"gait":"walk"}` or `"gait":"run"`.
The contract lists the actual step verbs and required target/duration/hand fields.
It describes syntax, not additional verified capabilities. Unsupported actions
still fail before replacing work and return the allowed verbs and a mapping hint
when the mistaken verb was a gait label.

Use `session_info` / MCP `people_session(action="info")` before planning. Writes
accept optional `session_id`, `episode_id`, `controller_epoch`, `command_id`, and
`attempt_id`. MCP exposes these fields too. Supply the observed session/episode
to reject work prepared for a previous world. Legacy unscoped writes remain
compatible; they cannot identify an earlier runtime session on their own.

`request_id` identifies the exact tool call and its parameters. Retry an uncertain
delivery with the same parameters and request ID. A different payload requires a
new request ID. Optional `command_id` groups one user instruction's calls;
`attempt_id` identifies a planning/recovery attempt. It is not an instruction to
retry automatically. The MCP wrapper namespaces request IDs by its configured
logical controller ID. Keep `SIMPEOPLE_CONTROLLER_ID` stable across reconnects.
Use a fresh command prefix in each independent host conversation. Episode reset
retains request history so uncertain reset deliveries can still be retried; it
does not make an old request ID available for a new payload.

A logical actor ID may be reused after despawn/reset, but its native USD path is
unique per incarnation. Behavior can retain an old agent when the physical path
is reused during Play; checking only the new logical instance ID did not catch
that old root. Use the `prim_path` returned by spawn rather than constructing an
actor path. Existing instance bindings, task IDs and resource tokens still fence
the logical lifetime. Blocker labels and camera focus continue using actor IDs.

Despawn disables updates on the explicitly retired native agent and removes its
Behavior API in the stronger SDK session layer before deleting the managed USD
container. A cached SDK handle can remain disabled after deletion. The native
lifecycle probe checks its enabled state and walks to the retired actor's old
position, in addition to checking the new actor's actual spawn location.

Successful receipts are cached in process. A replay is allowed only while the
receipt's resulting episode and control generation are still current. The same
reset request may legitimately contain the pre-reset episode and acquisition
epoch: its replay returns the original post-reset receipt. Later resets or
controller changes invalidate that receipt. Replaying release never reacquires
ownership. Restart creates a new session; there is no durable exactly-once claim.

Every spawn creates a fresh `actor_instance_id`, even when its actor name is
reused. Bind `run_activity` to that optional instance ID to reject a plan for a
deleted actor. An old task query does not report a replacement actor's observation.
Resource and queue leases also carry the instance and activity generation. Late
cleanup cannot release a newer lease belonging to the same actor name.

`if_busy="reject"` preserves an active or physically unsettled activity and returns
`ACTOR_BUSY`. The default `"supersede"` preserves the existing replacement API.
Replacement invalidates the old plan immediately, recording
`physical_stop_verified=false`; it does not certify that the body has stopped.
An explicit cancel is accepted first, then settles from actual native speed below
0.15 m/s for 0.5 simulation seconds, with seat cleanup complete. Only then is the
task `cancelled` with `physical_stop_verified=true` and `stop_settled_sim_time`.
Inspect `STOP_FAILED` if physical stop does not settle within its existing budget.

`people_crowd_state` also returns `seat_cleanup` for each actor. A pending cleanup
includes its original simulation-clock start, 15-second deadline, remaining
budget, exit target/horizontal distance, backend task state and available traffic
blocker details. Its phase distinguishes standing transition, exit selection,
route submission/waiting/execution and final settling. A running route without a
submitted movement task is `exit_route_pending`. Missing or stale observations remain explicit;
unknown blocker IDs are not inferred from nearby people.
When available, `route_goal_m` retains the submitted route goal separately from
the current exit marker's `exit_position_m`; moving a marker does not relabel the
already submitted route.

The cleanup snapshot is read-only and does not reset a deadline or retry a route.
After an activity fails, physical seat cleanup can continue with zero remaining
budget until the occupant clears. The original activity outcome stays separate
from that resource cleanup; query its task ID for the terminal result. These
diagnostics do not add a new animation or routing qualification.

`on_blocked="report"` keeps ordinary supervision and native avoidance. The
reservation backend additionally supports `replan_or_report`: after a persistent
wait it can stop, verify settlement, release future claims and replan to the same
goal. The activity's original deadline is retained. At most two explicit recovery
attempts are allowed across the activity. Existing queue resubmissions after a
failed native slot/exit task share that two-attempt budget, including in `report`
mode. Reacquiring a completed queue target after native idle avoidance moved the
body away also consumes this budget; ordinary capacity polling and SDK avoidance
are not recovery attempts.
Unsupported backends still reject the opt-in policy before replacing an activity.
Budgets are frozen in `configs/runtime_policy.json`.

`seat_egress_selection_enabled` is a separate **default-off experiment**. Before
starting chair exit cleanup it checks every registered exit's actual NavMesh
path against current body clearance and reservation claims. A clear original
choice stays unchanged; an alternative is considered only when the original
path is currently rejected. If none is clear, ordinary waiting and its existing
budget remain. Selection does not reserve cells, change the task deadline or
release the seat. The normal native route, fairness admission and measured exit
settlement still decide completion. `seat_egress_selected` records the original
choice, all considered paths and the selected target. Native paired acceptance
is pending; this option is not an established reliability improvement.

The opt-in `candidate_repair_enabled` search keeps the ordinary candidate first.
Only a physical rejection can trigger one filtered alternative search per retry;
fairness-only rejection cannot trigger this branch. The alternative is admitted
through the same body, exclusive-claim and older-fence checks. It keeps the
original goal, route age and deadline and never acquires or releases leases in
the search helper. `traffic_candidate_rejected` records the actual rejected
segments, blocker positions and distances. `traffic_candidate_repair` records
the proposal and admission result. These internal searches are not high-level
recovery attempts and do not reset the two-attempt activity recovery budget.
This experiment is off by default; it has not established a general speedup.

The separate `goal_claim_wait_enabled` option treats an exact destination held
by another physical lease as a destination wait. If the ordinary native prefix
cannot be admitted, it waits for the destination rather than chasing substitute
end nodes around that held point. Its fairness scope covers the occupied goal;
ordinary corridor protection resumes with the same priority age when it clears.
Existing holders keep their real leases and drainage checks. No TTL or timeout
frees occupancy. `traffic_goal_lease_wait` records owner routes, actual owner
positions, held cells and the original wait age. This option is also off by default.

The read-only [interaction registry](scene_interactions.md) adds explicit target
geometry, live occupancy and advisory preflight. An optional step-level
`interaction_revision` binds supported interactions to that geometry and rejects
stale plans both before replacing a task and during execution.

Traffic fences retain the original route age through partial movement grants.
An older request can fence a conflicting newcomer even while it is physically
infeasible. A destination occupied by a body is fenced separately from corridor
contention: its wait does not monopolize unrelated access. When the destination
clears, corridor protection resumes with the original age and current drainers.
`traffic_guard_scope_changed` and `blocked_details.admission_scope` expose this.
Preexisting occupants can drain, including a same-generation body
vacating the older request's occupied destination without leaving the entire
route envelope. If drainage needs a short initial segment inside the zone, a
full path with clear connectors and edges through its exit must first be verified
against the current snapshot. `traffic_drainage_granted` retains that proof.
This exception never bypasses actual body clearance or physical claims.
Wait-budget expiry reports a violation; it does not free occupancy.
The experimental `dynamic_edges_enabled=true` path search checks both nodes and
connecting edges against current claims and body clearance. It is disabled by
default: a paired native cancellation workload regressed its original deadline
with the filter enabled. Execution always checks actual segment clearance and
exclusive claims, including when this search filter is off.
The separate experimental `tail_release_enabled=true` option reclaims cells
wholly behind an observed, straight continuous native segment within one grid
row or column. It is off by
default and has no effect on segmented travel. Turns, reversals, short segments
diagonals changing both grid indices, and requested speeds above 3 m/s retain
their entire claim. A 2 m trailing plane
plus 5 cm margin is measured against cell corners, never just their centres.
Only this route's active body-generation guard and matching native task may be
trimmed. The occupied body, destination and all future cells remain protected;
the original fairness age and task deadline remain unchanged.
The full current grid footprint must fit inside the remaining original claim.

`diagonal_tail_release_enabled` is an additional **default-off, unqualified**
extension and requires `tail_release_enabled`. It permits only straight,
constant-height diagonals under the existing speed, sample-gap, body-coverage
and two-metre trailing constraints. Before motion, line/expanded-cell
intersection conservatively adds any swept cells missed by sparse samples;
those cells must pass ordinary exclusive admission too. Missing initial
coverage disables reclamation. `traffic_tail_tracking.original_cells` records
the actual initial ownership for independent interval-based auditing.

The diagonal experiment freezes further reclamation on a forward sample spike
inside the already enforced path bound; the spike cannot justify additional
cell releases. The body must still be inside owned cells,
and retreat, off-path motion or missing samples retain the existing stop guards.
Axis-only mode keeps its previous spike handling. Frozen claims and the actual
spike remain in the journal. Fresh small native positive, cancellation and
obstacle probes are required before queue/crowd tests or any default promotion.
Even a small diagonal deviation can cross a cell corner: before any removal this
disables reclamation for the segment; after a removal it requires a safety stop.

After reclamation, retreat, path deviation or an observation gap requires native
stop and measured settlement before a `TRAJECTORY_DEVIATED` result. The remaining
claim is held while braking. A forward position sample spike inside the still
owned cells freezes further reclamation for the segment; retreat and deviation
monitoring continue. `traffic_tail_tracking`, `traffic_tail_released`,
`traffic_tail_tracking_frozen` and `traffic_tail_safety_brake` expose this history.
There is no expiry-based release and no second root/skeleton writer.
Use `scripts/audit_tail_release.py RUN --output RUN/tail_audit.json` to match
removals to native starts and actual root samples, including cell-corner clearance,
body/goal retention and monotonically shrinking claims. Zero removals are marked
unverified execution; passing a non-triggering workload cannot validate this path.
The [1113 native experiment](../reports/ITERATION_20261113_T2_TAIL.md) retains an
enabled queue-cancellation failure alongside its disabled control. This option
has not passed the release workload and remains off by default.

Fallback paths retain the existing bounded positive
cost for revisiting nodes at all crowd sizes, including small congested queues.
Necessary retreats remain possible. The verified NavMesh remains unchanged.

Physical queues now distinguish admitted slots and a bounded FIFO outside queue.
A vacancy is assigned to the oldest outside ticket immediately, even before that
actor next polls. State includes ticket identity, rank, first request time,
capacity, blockers and the current deadline. Seats use the same ticket mechanism
for their existing resource leases. A step's admission time consumes its timeout
budget, rather than starting a fresh timeout after acquiring the resource.
Completed queue service remains complete while awaiting an exit; restoring a
displaced position does not start a second service or emit a second service start.

Cancelling or replacing a physical queue member keeps its lease until it actually
clears the queue and settles. New activities wait for that cleanup. Two failed
exit attempts or 15 simulation seconds produce a cleanup error with occupancy
retained; expiry never makes a body disappear. After an external obstruction is
removed, an explicit new activity can request a fresh cleanup budget without
reviving the old failed activity. An actor's current `queue_cleanup` is queryable.
The reported physical stop is a measured settlement event, not a permanent lock
on native idle/avoidance motion.

All tool attempts, including rejection and replay, have result events. Errors
include `code`, `stage`, `retry_class`, and correlation fields in `details`. MCP
returns them as structured `CallToolResult(isError=true)`. Stages classify where
the error occurred; they do not authorize an automatic retry. Native end events
preserve the SDK's raw `task_id`, add `native_task_id`, and use `logical_task_id`
for the supervisor task when unambiguous. Reused native IDs are explicitly marked
`ambiguous`, rather than being assigned to whichever task is currently active.

```bash
python3 scripts/analyze_command_outcomes.py runs/RUN_ID/events.jsonl \
  --output runs/RUN_ID/command_outcomes.json
```

The analyzer groups recorded command/request/task/attempt IDs and checks paired
request results. It does not infer omitted command IDs, prove natural-language
understanding, or promote accepted/registered states into successful execution.

On a persistent native traffic cycle, `traffic_wait_cycle_snapshot` retains the
current claims, fair-gate ages/scopes/drainer tokens, active route state, body
generations and already-cached navigation edges. Extraction reads memory on the
Kit thread; it never queries new edges, frees claims, changes priority or moves
an actor. Observations were taken at tick start, while route state includes
decisions during that tick. They are labelled separately; an earlier sampled
native task ID must not be relabelled as the post-command SDK task.

`traffic_body_instance_id` is a backend generation, not Engine's
`actor_instance_id`. Missing generations, nonfinite values and unsupported
serialization are explicit. A failed extraction emits
`traffic_wait_cycle_snapshot_unavailable` and leaves arbitration running. Cached
edges are partial, so the snapshot cannot alone prove that an escape is safe.
CPU extraction tests do not certify a native capture or a solved waiting cycle.
