# Native head and hand gestures

`head_look` calls Behavior's head-look task. Legacy `look_at` continues to turn
the body through facing Idle. `reach_hand` calls the native single-hand task.
Both run on the Kit main thread under the actor's existing controller; there is
no external root or bone writer.

Query `people_list_actions` for the selected actor first. Only exact asset,
motion-library, rig and runtime revisions in `configs/native_gesture_catalog.json`
are accepted in normal mode. The current qualification covers `default` and
`female_adult_business_02` on Z-up, metre stages. Other combinations report
unverified. Honor the returned `domain` and `max_hold_duration_s`. After the
129-file execution integration, the original default-Idle **0.6-second domain
requires fresh qualification** and reports discovered. The qualified process-start
`--idle-profile basic` domain allows **2 simulation seconds**, only with effective
Idle tags exactly `["Idle"]`, a 1/30 s response interval, zero response jitter,
and the exact implementation, asset and runtime revisions recorded in the
catalog. Changing those conditions does not inherit this qualification. Query
the actual actor; a previously loaded stage does not acquire this startup mode.

Move to an interaction's approach and confirm actual arrival before submitting
the gesture. This first version validates the actor's current settled standing
pose, not a hypothetical pose after a distant move in the same plan. Targets
behind the actor, outside arm reach, outside the sampled domain or inside another
managed body proxy are rejected before replacing a valid old activity.

Use actual queried target coordinates in an activity:

```json
{
  "request_id": "right_hand_probe",
  "actor_id": "operator",
  "steps": [{
    "action": "reach_hand",
    "hand": "right",
    "target": [0.0, -0.3, 1.2],
    "duration_s": 0.6,
    "timeout_s": 8
  }]
}
```

`hand` is required (`left` or `right`) for `reach_hand` and rejected on other
actions. `head_look` takes the same target/duration/timeout fields without `hand`.
`people_perform` also accepts coordinate targets and the optional hand field.

Workstations only gain these actions when explicitly declared. `look_prim_path`
and `palm_left_prim_path` / `palm_right_prim_path` provide their anchors.
`people_validate_interaction(..., hand="right")` resolves the chosen hand target.
For a bound activity, include the workstation `resource_id`, returned
`interaction_revision` and exact returned anchor coordinates. Missing anchors,
wrong coordinates and changed revisions are explicit failures. Existing
workstations retain their original default actions.

Completion requires actual joint alignment for 0.3 s, followed by the requested
continuous hold, native cancellation/return, and 0.5 s settlement. Lost alignment
restarts the hold without extending the original deadline. Hold checks include
root displacement <=0.05 m, facing change <=5 degrees, head-direction error
<=12 degrees or wrist error <=0.05 m, and active-arm segment-length change <=2%.
The head direction is calibrated from the asset bind pose; eye motion is not
measured. Idle can shift weight, so this does not promise a fixed root or feet.

Head return uses another owned native look task to reach forward neutral before
that return task is cancelled. It does not wait for an arbitrary old Idle head
pose to recur. Failed tasks also finish their pending native return. A return
that cannot settle has a finite cleanup limit and explicit failure; a still
extended hand cannot be reported as a physically settled cancellation.

The hand endpoint is the native **Hand joint / wrist proxy**. A `palm_*` anchor
does not imply palm-surface contact calibration. Small joint error is not a skin
contact, grasp, manipulation or force certificate. Source assets, generated
motion, moving-person tracking, seated gestures and whole-body mesh clearance
are outside this qualification.

Evidence and retained failures: [1113 gesture report](../reports/ITERATION_20261113_GESTURES.md)
and [two-second qualification and six long tests](../reports/ITERATION_20261114_GESTURE_DOMAIN_AND_LONG_CLOSE.md).

An opt-in development probe can compare a preloaded generated standing base with
the native facing Idle. `probe_gesture_runtime.py --experimental-hold
--hold-seconds 2 --experimental-base-clips <local-export-directory>` marks only
that run's catalog discovered, imports before Play and keeps both tasks owned by
Behavior. The base task must also end during cleanup, and may not replace a newer
body action. This experiment is rejected in strict mode and does not change the
installed qualification. The verified two-second startup domain above uses
normal native Idle and does not use this experimental base. `--pose-contexts` retains four consecutive
actual full-SDK poses per hold for inverse-retarget research; it does not infer a
PoseBridge from theoretical source clips. See the [motion progress record](../reports/ITERATION_20261113_MOTION.md).
