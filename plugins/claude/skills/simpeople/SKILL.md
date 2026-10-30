---
name: simpeople
description: Arrange and control animated people or crowds in an Isaac Sim scene through SimPeople tools; use for creating people, assigning activities, live goal changes, crowd summaries, cancellation, and simulation evidence.
---

Use the installed SimPeople MCP tools. Runtime tasks continue independently of the MCP connection. Do not write USD transforms or bones from another script.

1. Call `people_session` with `action=info`, then `action=preflight`. Check session/episode identity, public coordinate frame, NavMesh, semantic places and asset availability. A missing NavMesh, seat calibration or asset is a concrete blocker to report. Never silently substitute another scene or idle animation.
2. Inspect assets and action capabilities before planning. `discovered` is not verified. Functional `sit` and geometric quality certification are separate. Arbitrary rigs and chairs are not automatically compatible. Read `docs/acceptance_criteria.md` from the runtime checkout when assessing capacity; a mode name does not establish real-time throughput.
3. Acquire control with `people_session(action=acquire, request_id=...)` before writes. If another client owns it, keep observing. Only take over when the user requested it; read current epoch and use explicit `action=takeover, expected_epoch=...`. Local ownership coordinates clients; it is not authentication.
4. For one actor, validate the complete activity before submitting. For crowds, use `people_crowd(operation=run_activity, selector=..., steps=...)`, or individual `items`. Select by `actor_ids`, `role`, `group`, or `region_m=[xmin,ymin,xmax,ymax]`. Batch size is at most 100; inspect each item because partial acceptance is possible. Spawn batches require explicit items with actor IDs, assets and anchors.
5. Every write requires a unique `request_id`. Retry uncertain delivery with the same ID and identical parameters. Accepted means submitted; poll each returned task ID until `succeeded`, `failed` or `cancelled`. Do not report accepted plans as completed animation.
6. For normal monitoring call `people_crowd(operation=state)` for summary and paginated actors. Request `details=true` only for specific actors. Read `people_crowd(operation=events, after=cursor)` incrementally; if `history_gap=true`, refresh state because bounded event history has rolled over.
7. To change goals, submit validated new activities for only the selected actors. A replacement cancels their prior activity and invalidates its control epoch. Other actors continue. After reconnecting, query current runtime state before retrying old intentions under a new ID.
8. Cancel with `people_cancel` or a crowd cancel batch; poll until settled. Cancellation acknowledgement alone does not prove the actor stopped. Seat occupancy remains reserved through stand-up and egress. Pause freezes simulation-clock waits. Reset removes managed actors and changes episode identity; it is not an ordinary cancel.
9. Retain real tool replies, task outcomes, trajectories and video for an audit. Video encoding rate is not measured runtime FPS. Report actual RTF and wall-time update rate separately. Traffic waiting, animation sliding and long render frames are different observations.

Use public Z-up metre coordinates reported by preflight. A move step may include `via` waypoints. `people_signal_event` consumes explicit supplied events; it does not imply robot sensors exist. Crowd follow remains blocked where not accepted. No arbitrary Python evaluation is exposed by this plugin.
