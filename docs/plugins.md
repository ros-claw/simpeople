# SimPeople agent plugins

SimPeople is one Isaac runtime with thin Codex and Claude Code adapters. The runtime owns long activities and native animation; the host submits plans and reads actual outcomes. MCP disconnects do not delete activities.

## Install on the Isaac host

Clone `https://github.com/ros-claw/simpeople`, create and activate a Python 3.10+ virtual environment, then run:

```bash
python -m pip install -e '.[mcp]'
export SIMPEOPLE_ROOT="$(pwd)"
export SIMPEOPLE_ISAAC_DIR=/path/to/isaac-sim
export SIMPEOPLE_CHARACTER_DIR=/path/to/Isaac/People/Characters
export SIMPEOPLE_ENDPOINT=http://127.0.0.1:8768
simpeople doctor --isaac-dir "$SIMPEOPLE_ISAAC_DIR"
```

Editable installation is the supported distribution for launching Isaac; a wheel alone does not contain the scenes, cache preparation scripts and configuration. NVIDIA assets are not redistributed. Prepare the asset cache following the root README before creating people.

Start an independent session with `simpeople serve --scenario industrial_life --gpu 0 --duration 3600`. To use an existing scene, load `extensions/rosclaw.simpeople` in Kit and supply semantic locations; the extension preserves the scene's original root layer. Both modes need native Behavior/Navigation, a baked NavMesh, compatible assets, and calibrated seats. Run preflight after connecting. The public API uses normalized Z-up metres even if the input USD stage uses another supported axis or scale.

## Codex

The portable package lives in `plugins/codex` (`plugin.json`, `mcp.json`, `skills/`). Its MCP command is the installed `simpeople mcp`, resolved from the host PATH. The same server can be registered explicitly with current CLI:

```bash
codex mcp add simpeople -- simpeople mcp
codex mcp list
```

Keep the controller executable on the host PATH and follow the included SimPeople skill. Codex filters the environment passed to an MCP subprocess: custom `SIMPEOPLE_ENDPOINT` and `SIMPEOPLE_CONTROLLER_ID` values must be listed in the MCP server's `env_vars` or set explicitly in its `env` map; setting them only in the parent shell is insufficient. Manifest schema validation and actual natural-language host acceptance are separate evidence; check the optimization report for their recorded status.

## Claude Code

For a local checkout:

```bash
claude --plugin-dir /absolute/path/to/simpeople/plugins/claude
```

The public repository contains a marketplace manifest:

```text
/plugin marketplace add ros-claw/simpeople
/plugin install simpeople@ros-claw-simpeople
```

`claude plugin validate plugins/claude` checks the package without authentication. Real natural-language tasks require a signed-in Claude host. Install or login using the provider's own CLI; do not put credentials in this repository or plugin configuration.

## Control and monitoring

`people_session(info/preflight)` is read-only. Acquire ownership before writing. Another host may observe, but explicit takeover must include the current generation and user intent. The packages set stable `SIMPEOPLE_CONTROLLER_ID` defaults (`simpeople-codex` and `simpeople-claude`) so each host retains its logical identity across MCP reconnects. Override these defaults with distinct IDs when running independent instances of the same host. IDs coordinate trusted local clients and are not an authentication boundary.

`people_crowd(state)` returns counts and a bounded page. Use selectors (`actor_ids`, `role`, `group`, `region_m`) for activity/cancel batches. Batch acceptance is per item and is not atomic. Use task IDs to confirm terminal results. `people_crowd(events)` exposes an incremental bounded cursor; refresh state when history rolls over. Full durable events remain in the run journal.

Modes describe intent: interactive, generation, audit and experimental. Actual real-time and population capacities are published independently. Continuous corridor travel is opt-in while population regression is being validated; the conservative segmented profile remains available.

For the standalone motion-quality profile, add `--traffic-profile corridor` to the serve command. The attaching extension uses direct native navigation and its own session overlay. It does not install the factory-specific reservation scheduler into a user's scene; attached-scene population capacity requires separate validation.

### Unattended Codex CLI validation

The local 0.166.0 reference host discovered and installed the portable plugin. Its default MCP approval policy initially rejected unattended calls. A scoped, per-invocation MCP override was used for the authorized acceptance run; the filesystem remained read-only:

```bash
codex exec --disable apps -s read-only \
  -c 'mcp_servers.simpeople.command="simpeople"' \
  -c 'mcp_servers.simpeople.args=["mcp"]' \
  -c 'mcp_servers.simpeople.env_vars=["SIMPEOPLE_ENDPOINT","SIMPEOPLE_CONTROLLER_ID"]' \
  -c 'mcp_servers.simpeople.default_tools_approval_mode="approve"' \
  'Inspect the SimPeople session and perform the requested test activities.'
```

Use this approval setting only for a local runtime whose managed actors you intend the agent to control. It scopes approval to this server and does not bypass the host filesystem sandbox. Interactive hosts can use their usual tool approval UI instead. The nested plugin MCP policy override in current public documentation did not take effect in this installed CLI build; the explicit server configuration above was verified separately. See the recorded host test outcome before treating installation as natural-language acceptance.

The first native host trial correctly refused to act when its custom endpoint was not forwarded. The corrected trial explicitly supplied the local endpoint and stable controller ID in the server environment. Default plugin packages target loopback port 8768; custom sessions require this host configuration. No user credentials are needed in these variables.
