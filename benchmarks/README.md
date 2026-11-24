# RuntimeBench, first iteration (2026-11-10)

This directory freezes requests, rather than relying on one shared random seed.

The complete **input** matrix is now frozen under
[`release_inputs/industrial_pair_v2`](release_inputs/industrial_pair_v2/matrix_manifest.json):
wide/narrow layouts × 10/30/50 actors × seeds 17/42/99, with two dependent cycles
per actor and a fixed 600-second horizon. There are 18 cases and 1,080 planned
requests per runtime version. These files do not certify nominal feasibility or
replace actual baseline/candidate executions. Numeric inputs falling inside the
observed narrow-layout wall clearance are explicitly mapped in the manifest;
both runtime versions must use the exact same frozen case bytes. Unsafe semantic
targets require a separately revised scene, rather than an implicit adjustment.

The original [v1 inputs](release_inputs/industrial_pair_v1/matrix_manifest.json)
and failed native preflight are retained. Its narrow layout put `queue_2` exit0
inside the south wall, failing all nine narrow cases. The separate
`industrial_narrow_release_v2` scene moves only that exit from `[0,-15,0]` to
`[-1.25,-15,0]` and records the semantic revision. All18 v2 cases pass actual
static NavMesh preflight in `iter1114r-release-fixture-v2-preflight-01`; this is
not crowd capacity or completed workload evidence. V1/V2 cases cannot form a
runtime improvement pair. The input generator now checks every interaction exit.

To freeze new inputs from actual observed semantics into a new directory:

```bash
python3 scripts/freeze_runtime_release_cases.py \
  --wide-semantics runs/YOUR_WIDE_RUN/scene_semantics.json \
  --narrow-semantics runs/YOUR_NARROW_RUN/scene_semantics.json \
  --output YOUR_NEW_INPUT_DIRECTORY
```

Before scheduling the release matrix, run the static fixture preflight in the
installed Isaac runtime, using a new run ID and an available GPU:

```bash
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/probe_release_fixture.py \
  --workspace-root "$PWD" --source-root "$PWD" --gpu 3 \
  --matrix benchmarks/release_inputs/industrial_pair_v2 \
  --run-id YOUR_NEW_FIXTURE_RUN
```

This preflight records actual paths and both endpoint projection errors for
every spawn, movement waypoint, seat approach/alternate exit and queue slot/exit.
It spawns no actors. Static connectivity does **not** prove crowd service,
standing transitions, capacity, deadlines or a successful 600-second workload.
Baseline-B0 and one final candidate still require 18 actual runs each. The
current six default/basic Idle comparisons are a separate experiment.

`scripts/audit_runtime_release_matrix.py` checks the eventual 18 runs per version
against these inputs and explicit frozen source manifests. It rechecks snapshot
bytes, request IDs and conservation, actual capture totals, two-cycle completion,
waiting budgets and paired root geometry proxies. Missing/duplicate/changed cases
fail the matrix. Baseline failures remain valid comparison observations; a failed
baseline is not a reason to discard its matched candidate. The script reports
the 2% request target and the stricter every-actor/two-cycle check separately.
Its runtime result does not certify performance improvement or the full project;
paired waiting distributions and unserved lower bounds, MotionBench and actual
host acceptance retain their own gates.

For long comparisons, freeze a shared execution workspace before launching the
first baseline case. This copies the driver, its helper modules and offline
analyzers, and declares local `assets`/`runs` symlinks to the real workspace.
Existing asset files are referenced unchanged. Both versions must use **the same
shared workspace**; using different alias paths can change asset URI metadata in
the runtime contract. Development-tree edits then leave the driver bytes intact.
Each runtime source still needs its own checked `source_manifest.json`.

```bash
python3 scripts/run_runtime_release_version.py prepare \
  --workspace-root "$PWD" --matrix benchmarks/release_inputs/industrial_pair_v2 \
  --output YOUR_NEW_SHARED_DIRECTORY
python3 YOUR_NEW_SHARED_DIRECTORY/scripts/run_runtime_release_version.py run \
  --shared-workspace YOUR_NEW_SHARED_DIRECTORY \
  --source-root YOUR_FROZEN_BASELINE_B0_SOURCE \
  --run-prefix YOUR_UNIQUE_BASELINE_PREFIX --idle-profile default \
  --case-ids release_wide_10_seed17_v2 \
  --fixture-run runs/YOUR_SUCCESSFUL_FIXTURE_RUN \
  --state-output YOUR_NEW_STATE_FILE --gpu 3 --port 8898
```

The runner requires an actual passed static fixture result bound to this exact
matrix. Start with one complete 600-second case to inspect the harness on the
original baseline. An explicit subset remains partial; omitting `--case-ids`
selects all18. Failed native outcomes remain unchanged and can be valid baseline
observations; a nonclosed harness stops the batch. Each run uses a new ID and
retains its own source snapshot, full synchronized capture and analysis logs.
The runner never marks the overall release gate passed. Check storage and owned
native processes before continuing; do not launch a second job onto a busy GPU.
The native actors continue to be controlled by Isaac Behavior / Navigation.

- `smoke10_closed_v1`: 10 actors, two complete move/wait/return activities each,
  90 simulation seconds, full 1080p capture.
- `population{10,30,50}_closed_seed17_v1`: two role cycles per actor, generated
  once from the industrial semantics with independent actor/cycle random streams.
  These files are workload definitions; their existence is not a native pass.
- `open_queue2_v1`: explicit overlapping arrivals and a bounded replay queue.
  This queue belongs to the benchmark driver, not the scene's physical service
  queues. It does not implement T2 fairness or bounded navigation recovery.

`closed_loop` preserves activities and dependencies. Actual submission times may
change with execution speed. `think_s` is measured after the predecessor's actual
finish. `open_arrival` preserves scheduled arrival times; a busy actor is rejected
or queued according to the frozen policy. Ordinary cases cannot silently replace
tasks. Only explicit replacement/cancellation cases may use `supersede`.

Every planned request remains in the results, including those never submitted.
Finite deadlines count unfinished work as unsuccessful. A continuous observation
window censors work still running at its end; it does not count that work as a
success or a failure. Earlier request deadlines still apply. Results retain actual
eligible/submitted/admitted/terminal times and lower bounds on unfinished waits.

Run a fresh native measurement (never reuse an existing run ID):

```bash
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/bench_native_runtime.py \
  --run-id YOUR_UNIQUE_RUN_ID --gpu 3 --port 8872 \
  --case benchmarks/workloads/smoke10_closed_v1.json
```

`--source-root` can select an earlier frozen source tree containing `src`,
`configs`, and `schemas`. Both versions use the same snapshotted replay harness.
The case's semantic scene revision must match the actual generated scene. The
driver retains source hashes, live binding docstrings, readiness, events,
trajectories, resource samples, frames and all request outcomes.

For a world already running through the bridge, with all case actors created at
their specified initial positions and no autonomous population scheduler:

```bash
python3 scripts/replay_workload.py benchmarks/workloads/open_queue2_v1.json \
  --endpoint http://127.0.0.1:8768 --output runs/YOUR_REPLAY_OUTPUT
```

This command does not spawn/reset the world. Use an unowned session or the same
logical owner as the bridge client. Offline `capture_runtime_contract.py` only
inspects the installation; the native driver captures freshly loaded APIs.

The historical stochastic 50-person / 600-second baseline is separate evidence.
It is not a frozen paired workload and cannot establish an improvement against
these cases. Shared GPU totals do not certify exclusive performance, and a passed
smoke test is not a 30/50-person reliability or real-time capacity claim.

## T2 probes

`r3_queue*_v2` adds a distinct destination after service so actors do not park in
both exits forever. The original queue-only v1 fixtures and their failures are
retained as externally blocked cases, not used as a baseline for a v2 speedup.
`r5_queue_cancel10_v2` also keeps the positive actors' destinations clear of the
cancelled outside actor. Comparing different fixture versions cannot establish
an implementation improvement.

`scripts/audit_runtime_probe.py RUN_DIR --output PATH` checks actual outcomes,
ticket bounds, original recovery deadlines, unchanged recovery targets and the
dynamic-box root/AABB proxy when applicable. It retains mismatches in its JSON;
running the audit successfully does not mean its functional checks passed.

`r2_narrow*` uses a diagnostic layout with walls reaching the floor boundaries:
the existing door is the only crossing. Production `industrial_scene` is unchanged.
The same diagnostic scene helper is frozen with the harness and works against an
older runtime source tree too.

Native fault probes may set `stop_when_complete=true`. They finish only after all
frozen terminal/error/physical-stop predicates, scheduled events and checkpoints
are satisfied. Their declared duration is a maximum horizon; the actual duration
and frame count are reported. Fixed-duration comparisons keep the full window.
Continuous 30/50-person 120-second screens cannot stop early. Their incomplete
cycles remain censored; these screens do not certify the 600-second release gate.
Fault/checkpoint/startup-policy cases require `bench_native_runtime.py`; the simple
live replay CLI rejects these fields instead of silently omitting them.

Event-bound fault experiments additionally require
`--diagnostic-native-release-triggers`. Their typed `trigger` selects either the
first actual eligible diagonal release by an exact owned native task, or a delay
after another fault was actually applied. Default workload readers reject these
events. Native release faults require an active separate witness and preserve
route/body/world/control identities. Box placement is computed once on that
same committed path; the ordinary `move_prop` overlap check remains authoritative.
Frozen historical drivers are unchanged. CPU trigger tests do not establish
native fault coverage; actual release, braking, cleanup and witness traces must
still pass independent review.

`r6_recovery_*` tests a temporarily occupied target; native idle avoidance may
resolve it without a recovery attempt. `r6_dynamic_box2_v1` forces a kinematic box
into the single crossing, then removes it; this additionally tests actual braking
and the opted-in recovery path. `r7_overload10_v1` freezes outside capacity at two,
expects four task-level ADMISSION_FULL results and keeps them in the denominator.

Use `scripts/analyze_waits.py RUN_DIR --output PATH` for queue/traffic breakdowns.
Service wait, admission wait and request-to-exit latency are separate metrics.
Unfinished requests and their wait lower bounds remain beside served percentiles;
shutdown cleanup after the measurement cursor cannot turn them into successes.

`--policy-json benchmarks/policies/t2_edges_off.json` and `t2_edges_on.json`
provide a single-component ablation on the same frozen case. They differ only in
dynamic edge filtering. The driver snapshots the selected policy before hashing
source inputs; the case cannot also override startup policy. Compare original
deadlines, all planned outcomes, unfinished waits and geometry proxies alongside
served percentiles. An explicit failure is evidence, not a passed fairness gate.
The filter is an experiment and is disabled by default after the native paired
case regressed with it enabled; execution clearance remains mandatory.

`tail_off_v1.json` and `tail_on_v1.json` isolate straight-corridor tail
reclamation; dynamic edge filtering remains off in both. Reproduce the paired
native case with unique run IDs:

```bash
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/bench_native_runtime.py \
  --run-id YOUR_TAIL_OFF --case benchmarks/workloads/r8_tail_follow2_v2.json \
  --policy-json benchmarks/policies/tail_off_v1.json --gpu 3 --port 8881
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/bench_native_runtime.py \
  --run-id YOUR_TAIL_ON --case benchmarks/workloads/r8_tail_follow2_v2.json \
  --policy-json benchmarks/policies/tail_on_v1.json --gpu 3 --port 8881
python3 scripts/audit_tail_release.py runs/YOUR_TAIL_ON \
  --output runs/YOUR_TAIL_ON/tail_audit.json
python3 scripts/compare_workload_runs.py runs/YOUR_TAIL_OFF runs/YOUR_TAIL_ON \
  --output runs/YOUR_TAIL_ON/paired_functional.json
```

The v1 follow case is retained as a non-triggering control: its actual NavMesh
route curves around the industrial door post. The v2 fixture uses the existing
single-portal diagnostic scene and straight approach. Never compare v1 against
v2 to infer a code improvement. `r9_tail_cancel3_v1` and
`r10_tail_obstacle2_v1` inject cancellation/obstruction after the lead actor has
had an opportunity to release cells. Verify actual release-before-fault events;
a scheduled fault time alone does not prove this condition occurred.

The tail auditor independently checks native start identity, actual sampled root,
initial claim count, monotonic claim removal, retained body/goal footprints and
whole-cell trailing clearance. Inspect `execution_and_checks_passed`; zero
removals are explicitly not execution evidence. An audit process's exit code
does not certify that its JSON predicates passed.

`candidate_off_v1.json` / `candidate_on_v1.json` isolate one filtered retry after
a physically rejected candidate, keeping the tail experiment on in both.
`candidate_runtime_v1.json` selects this retry with tail reclamation off.
`r11_recorded_edge3_v1` uses an observed close-body configuration with a cancelled
body and independent witness. It must record an admitted alternative to count as
execution evidence. Waiting for a body to move can be faster than a conservative
detour; successful rerouting alone does not establish a throughput improvement.

`goal_wait_off_v1.json` / `goal_wait_on_v1.json` independently isolate waiting for
a held exact destination before searching substitute end nodes. Both keep the
candidate retry on and tail reclamation off. Compare every original deadline and
the fairness budget, including when a late runtime success remains a benchmark
`deadline_unfinished` result. Use `scripts/audit_candidate_repair.py` to match
admitted alternatives to native submissions, actual bodies, original goals and
unchanged route age. Its zero-execution result is explicitly unverified.
