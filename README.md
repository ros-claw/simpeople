# SimPeople

**Agent-controlled people and activities for Isaac Sim.**

SimPeople lets Codex, Claude Code, and other MCP clients create animated people, arrange activities, change selected goals, cancel tasks and inspect real simulation outcomes. A shared native runtime executes the activities continuously; an LLM is not called every frame.

The project combines a native Behavior/Navigation adapter, a task supervisor, a scene-attaching Kit extension, a CLI/MCP interface, and thin host plugins. It never teleports human roots or writes bones from a second controller to conceal failures.

## Install

Use Python 3.10+ for the controller and a separate Isaac installation for simulation. The Linux reference environment is Isaac Sim 6.2.0 RC with Behavior/Navigation 110.4.0. Other versions and arbitrary skeletons are not automatically validated.

```bash
git clone https://github.com/ros-claw/simpeople.git
cd simpeople
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[mcp,assets,video]'
export SIMPEOPLE_ROOT="$PWD"
export SIMPEOPLE_ISAAC_DIR=/path/to/isaac-sim
export SIMPEOPLE_CHARACTER_DIR=/path/to/Isaac/People/Characters
simpeople doctor --isaac-dir "$SIMPEOPLE_ISAAC_DIR"
python scripts/cache_assets.py
```

The supported launch installation is an editable checkout: scenes, configuration and cache preparation scripts live alongside the Python package. Do not install the controller's USD/MCP dependencies into Isaac Python. NVIDIA characters, animations and textures are not bundled; the cache script records official sample sources and hashes. Additional registered characters require the corresponding installed assets. Missing or changed resources are reported rather than silently certified.

Start a dedicated session:

```bash
simpeople serve --scenario industrial_life --gpu 0 --duration 3600
```

The bridge binds to loopback. To attach to an existing USD scene, load `extensions/rosclaw.simpeople` in Kit, configure semantic locations and a baked NavMesh, then run preflight. The extension manages its own overlay and preserves the original scene layer. The API reports normalized Z-up metre coordinates.

## Agent plugins

Codex:

```bash
codex plugin marketplace add ros-claw/simpeople
codex plugin add simpeople@ros-claw-simpeople
```

Claude Code:

```text
/plugin marketplace add ros-claw/simpeople
/plugin install simpeople@ros-claw-simpeople
```

For a local Claude checkout, `claude --plugin-dir /absolute/path/to/simpeople/plugins/claude` works without a marketplace install. The shared `simpeople` executable must be on the host's PATH. See [host setup and acceptance notes](docs/plugins.md) for scoped MCP policy configuration and the current test status.

Try: “Arrange people in this factory: some walk to workstations, some patrol, and some rest in verified seats. Stagger their starts. Then call only the patrolling group over to the machine.”

The agent inspects scene identity and capabilities, acquires write ownership, validates plans, submits batches and polls actual outcomes. Accepted is not completed. Runtime tasks survive MCP disconnects. Another host can observe; takeover is explicit and generation checked.

## Demonstrations

[Segmented/continuous motion comparison](https://github.com/ros-claw/simpeople/releases/download/demos-20261031/optimization_1031_motion_comparison.mp4) · [Actual walk/jog tour of twelve rigs](https://github.com/ros-claw/simpeople/releases/download/demos-20261031/optimization_1031_gait_demo.mp4) · [Seat fit comparison](https://github.com/ros-claw/simpeople/releases/download/demos-20261031/optimization_1031_seat_comparison.mp4). [Uncut native seat cycles and cancellation](https://github.com/ros-claw/simpeople/releases/download/demos-20261031/optimization_1031_seat_lifecycle.mp4). These are simulation renders; the six-second seat fit comparison uses stills, and playback encoding rate is separate from measured runtime throughput.

[Continuous 50-person factory excerpt](https://github.com/ros-claw/simpeople/releases/download/v0.2.0-preview/optimization_1031_crowd50_demo.mp4) shows 25 seconds from the accepted 600-sim-second run. It is simulation-time playback with a title overlay.

## API and quality

Twenty MCP tools cover single actors plus two compact management tools:

- `people_session`: identity, preflight and explicit controller acquisition/release/takeover.
- `people_crowd`: selected batches, per-item results, summaries, paginated details and incremental events.
- Existing actor tools: spawn, activities, move, perform, state, cancel, pause/resume, reset and recording.

Selectors support actor IDs, roles, groups and planar regions. One controller owns session writes. Local controller IDs coordinate trusted clients; they are not authentication credentials.

Native motion keeps final braking and cancellation settlement. The continuous corridor profile atomically reserves safe travel and falls back to conservative planning when needed. The segmented profile is the default. Continuous travel is opt-in: its large-crowd regression and real-time capacity are assessed separately.

To use the motion-quality profile in the supplied standalone factory, start `simpeople serve --scenario industrial_life --traffic-profile corridor --gpu 0 --duration 3600`. The scene-attaching extension uses direct native navigation; the factory reservation scheduler and its population evidence do not automatically transfer to arbitrary attached scenes.

Seat fit uses versioned profiles and actual native head/neck skinning audits. A queryable quality catalog binds evidence to asset, motion and chair geometry revisions. Functional action support, estimated foot contact quality and geometric interaction quality are separate claims.

## Evidence and limits

Read the [optimization acceptance report](reports/OPTIMIZATION_20261031.md) and [reference environment results](reports/REFERENCE_ACCEPTANCE.md). Each native run freezes its source inputs and retains events, actual root/joint trajectories, task outcomes and frame identities.

The reference v0.1 functional capacity was 50 people across three 600-sim-second seeds, with finite queue timeouts retained. That result does not establish 50-person real-time operation or certify every later motion-quality change. Current revision-specific quality, performance and host results are listed in the optimization report.

The 1031 preview adds twelve-rig walk/jog measurements and calibrated seat cycles, including cancellation. Its updated continuous profile passed a separate seed-17, 50-person, 600-sim-second run: every actor completed at least two role cycles, with no sustained root-overlap proxy or root jumps. The 160 successful activities, nine queue timeouts, one sit-step timeout and 48 shutdown cancellations are retained. This does not certify exact mesh contact or improved queue reliability.

Actual Codex natural-language acceptance passed three tasks. Claude installation and MCP connection passed; its natural-language tasks remain unexecuted because the reference host is not signed in. Full 30-person 1080p recording still runs below real time (the final default-renderer reference RTF was 0.220); no 24-update/second interactive population capacity is certified.

A separate 10-person 720p interactive-mode sample, with full RGB/encoding, measured RTF 0.345 and 10.34 actual updates per wall-clock second (153 ms p95 interval). It is a short throughput sample, not the 600-sim-second functional population gate.

Foot support is estimated from calibrated shoe proxies; it is not measured contact force or a universal no-slip guarantee. Head/neck skinned-vertex tests do not certify every triangle or whole-body collision. Arbitrary rigs/chairs, crowd moving-target follow, robot depth/LiDAR and force balance remain outside the accepted scope. Encoding FPS is not actual runtime FPS.

## Development

The [Shift Change film workflow](docs/shift_change_production.md) provides a frame-driven cinematic director, native actor blocking, an actual Codex batch-retarget take, source-frame tracing and decoded-PTS checks. It uses simulation-time capture and preserves real host latency separately.

```bash
PYTHONPATH=src python3 -m pytest -q tests
python scripts/build_plugins.py
```

All USD and Behavior mutations run on the Kit main thread. HTTP workers only enqueue requests. No remote Python evaluator is exposed. Source is MIT licensed; see [third-party notes](THIRD_PARTY.md) for separately installed NVIDIA assets and dependencies.
