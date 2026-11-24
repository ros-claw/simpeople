# CommandBench v1

This is a real host acceptance suite. The twenty frozen Chinese requests contain
14 positive commands and six negative commands. Each formal host run requires
three fresh CLI conversations and a fresh native episode per case: 60 attempts,
42 positive and 18 negative. Codex and Claude results are separate. A successful
pilot or an unauthenticated host never counts as a completed host matrix.

`commandbench_v1.json` freezes requests, initial actor positions/assets/groups,
preserved actors, wall/simulation/tool/token budgets, and native predicates.
`schemas/command-case.schema.json` validates each case. c01–c15 are development
cases; c16–c20 remain unexecuted until formal evaluation. Do not tune using their
outcomes before freezing the implementation. The response schema structures the
host's report, but a claim of completion does not satisfy a native predicate.

Coverage includes native movement/Jog, a sequential plan, sit/leave, group
creation, fixed group/region selection, subset reassignment, cancel/restore,
physical FIFO queue, shared seat, partial batch failure, nonexistent and
unreachable goals, disabled generation, unsupported force grasp/hold duration,
overload rejection, and a deliberately failed target followed by bounded repair.
The independent witness keeps its original patrol. Negative refusals cannot
increase the positive success-rate denominator.

## Running

Start a dedicated industrial runtime with continuous capture; do not use a user's
active production session. For example, choose an unused local port and run:

```bash
/data/omniverse/isaac-sim-6.2.0/python.sh scripts/kit_main.py \
  --scenario industrial_life --people 1 --serve --run-id UNIQUE_RUNTIME \
  --gpu 3 --port 8886 --traffic-profile corridor \
  --capture-profile full --duration 36000
```

After `ready.json` exists, the runner also queries the live session and checks its
PID, scene and versioned batch contract. It verifies actual ready native roots
against the frozen initial positions before submitting fixture activities and
again before starting the host. Metadata readiness alone is insufficient.
With the existing MCP controller environment:

```bash
.venv-controller/bin/python scripts/run_command_benchmark.py \
  --run-id UNIQUE_DEVELOPMENT --runtime-run UNIQUE_RUNTIME \
  --cases c01 c02 c03 c04 c05 c06 c07 c08 c09 c10 c11 c12 c13 c14 c15 \
  --repetitions 1
```

After development, freeze changes and run the full matrix:

```bash
.venv-controller/bin/python scripts/run_command_benchmark.py \
  --run-id UNIQUE_FORMAL --runtime-run UNIQUE_RUNTIME --formal
python3 scripts/analyze_host_acceptance.py runs/UNIQUE_FORMAL
```

The driver accepts `--host codex` (default) or `--host claude`. Claude's driver
and parser are implemented, but its authenticated natural-language matrix has
not run. Package, parser and unauthenticated startup tests do not qualify that
host. Check it without reading or changing a native session:

```bash
.venv-controller/bin/python scripts/run_command_benchmark.py \
  --host claude --host-preflight-only --run-id UNIQUE_CLAUDE_PREFLIGHT
```

Exit 2 means preflight is not ready; `host_preflight.json` lists the failed
checks. Inputs are frozen even for this check, and zero command attempts start.
The default executable is the locally installed Linux binary under
`.runtime/claude-linux`; `--host-binary` can select an existing executable. After
authentication and package checks pass, use a separate, unowned native runtime
with `--host claude --cases c01 --repetitions 1` for development, or `--host
claude --formal` for its full matrix. Never run both hosts against the same
live actor session at once. No fabricated model responses are executed.

For an unpublished local checkout, use the host's supported `--plugin-dir`
loading mode instead of relying on an older marketplace cache:

```bash
.venv-controller/bin/python scripts/run_command_benchmark.py \
  --host claude --host-plugin-dir "$PWD/plugins/claude" \
  --host-preflight-only --run-id UNIQUE_CLAUDE_LOCAL_PREFLIGHT
```

The driver runs the actual CLI package validator and compares the three plugin
contract files against the run's frozen source. It neither edits nor falls back
to the global installation. Keep the same `--host-plugin-dir` option for the
subsequent dedicated-runtime pilot or full matrix. Authentication is still
required; local loading cannot turn an unsigned-in host into an acceptance pass.

## Host binding and provenance

The driver enables the installed SimPeople plugin/skill, disables unrelated
plugins per invocation, retains read-only filesystem sandboxing, and captures
the installed package hashes. CLI 0.168 requires a complete explicit effective
MCP transport when overriding endpoint/env/approval. The runner mirrors the
installed `simpeople mcp` launcher and binds its endpoint, controller ID, frozen
Python package and local-server approval. This is declared as a compatibility
binding; it is not evidence that parent environment forwarding or nested plugin
approval works automatically. Global user settings and credentials are untouched.
See [host configuration](../../docs/plugins.md).

Claude loads a frozen session copy of the installed or explicitly selected local plugin and explicitly binds
its qualified `plugin_simpeople_simpeople` MCP transport. Its built-in tool set
is limited to Skill; restricted mode and `dontAsk` apply, and only the local
plugin MCP and `Skill(simpeople:simpeople)` are approved. Startup metadata must
show that exact connected transport, plugin path and tool boundary. Successful
Skill invocation is checked separately. This does not prove automatic marketplace
discovery or global plugin enablement.
Plugin changes after preflight or during the snapshot copy are rejected before
the first host attempt. Local and marketplace loading modes are recorded separately.

Raw Claude stream JSON is retained alongside a normalized grading view. Tool
results must match their actual tool-use IDs; duplicates, orphans, unfinished
calls, foreign tools, subagent events, changed sessions/models, missing structured
reports and missing usage fail the attempt. Only final aggregate usage is counted;
total input includes uncached, cache-write and cache-read tokens. See the official
[SDK message reference](https://code.claude.com/docs/en/agent-sdk/typescript) and
[cache accounting](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

Every run snapshots cases, schema, grader, driver and host packages. Each trial
retains the real JSONL, final report, process PID, native before/after states,
scene/resources, events and actual trajectory. Its native simulation-time window
can be matched to the runtime's continuous RGB and frame timestamps. Native
events after the scoring snapshot, including next-episode cleanup, cannot turn
unfinished work into success. Failed setup trials remain separate evidence.
Each independent trial supplies a unique request-ID prefix. Reusing the same ID
for a different episode/payload correctly produces `REQUEST_ID_CONFLICT`; reset
does not discard the runtime's idempotency history. Exact request retries keep
their original ID.

The host is asked to bind session/episode, validate normal activities, freeze
selected IDs, preserve witnesses and poll actual terminal results. The grader
requires successful session/preflight replies, verifies native tasks, final root
positions/stopping, cancellation settlement and resource leases, and rejects
unrequested actors, shell/file execution and changed witness tasks. Queue FIFO
is checked against actual service-start events. The limits are 900 wall seconds,
180 simulation seconds, 80 tool calls, 2,000,000 reported input tokens, 12,000
reported output tokens, and at most two repair events per command.
Wall/simulation/tool limits are monitored live; token limits are checked on CLI
usage after completion, not claimed as a provider-side hard cap. Codex cost
remains unknown. Claude's reported `total_cost_usd`, when present, is retained
per attempt; it is not independently verified billing or a price estimate.

The summary reports initial validation, first accepted activity terminals,
full-command completion without extra re-plans, bounded-repair completion,
native activity statuses, tools, usage and wall/simulation time. Intentional
cancellations/failures remain in the raw first-activity statistic. Confidence
intervals resample cases with all their repetitions together; they do not treat
the activities as independent language commands. Small pilots have no interval.

Repair accounting includes extra accepted requests (one batch counts once) and
distinct rejected plan proposals, including validation failures. Repeated delivery
of an identical rejected proposal is one variant. The deliberate invalid item in
the partial-batch case is expected, not a repair. Fixture seating cancellation and
the explicitly requested failed-target recovery have their own planned stages.

Formal gates are a complete 20×3 matrix, positive first end-to-end >=90%, positive
completion after bounded repair >=95%, and all negative cases protected. The
confidence intervals and per-category counts remain beside the gate results.
This small suite does not certify arbitrary instructions, new assets or scenes.
