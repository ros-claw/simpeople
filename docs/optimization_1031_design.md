# 1031 implementation notes

The product is a shared native Isaac runtime, a scene-attaching Kit extension, one MCP/CLI API, and thin Codex/Claude host packages. An agent submits activities; the runtime advances them and retains asynchronous tasks after transport disconnects.

## Motion

`--traffic-profile native` is a diagnostic direct-native baseline. `segmented` retains the conservative short-corridor behavior. Opt-in `corridor` atomically reserves a safe NavMesh polyline (full paths for small comparisons, bounded prefixes for large crowds), then submits continuous native movement with final braking enabled. If that corridor is unavailable, the conservative grid planner remains the fallback. Dynamic obstacle intersection still triggers native stop, settled braking and replan; cancellation still uses the native stop path. No root or joint transform is corrected manually.

Dense NavMesh samples are simplified within 0.01 m before submission; endpoints and genuine turns remain. Without this step, passing hundreds of tiny points to native `move_along` caused avoidable slowing in the first prototype. That failed quality comparison is retained separately.

`--quality-audit` records actual joint poses and rotations, native task IDs and requested steps with sample, simulation time, wall timestamp and video identity. Initial-idle calibrated heel/forefoot proxies estimate support using height and vertical motion. Horizontal foot velocity is never used to exclude sliding contacts. These contact estimates include transition sensitivity; native reference, distributions and worst footage are retained instead of asserting an uncalibrated universal slip threshold.

## Seat fit

`SeatProfile` records seat top/depth, hip effector, approach/egress semantics, oriented back geometry and revision identity. The generated 0.6 m deep seat's v3 hip effector moves 0.08 m toward its front while the authored back reclines 15 degrees. Its seat top and depth remain fixed. This aligns the native reclined sit pose with supported seating and gives the head/neck clearance. A v2 prototype moved the hips 0.24 m; it eliminated vertex penetration but was rejected on side-view review because the actor sat too far forward. External chair assets are not reshaped or automatically certified.

Audit mode checks head/neck spheres and a chest capsule. Fine auditing reconstructs selected actual asset vertices from skin weights, inverse bind matrices and native joint world poses. It supports classic linear skinning, verifies SDK-to-USD index mapping and uses the stage's unit/up-axis conversion. Unsupported bindings are reported as unavailable. Vertex penetration is a lower bound; this does not certify every triangle intersection, whole-body contact, balance, shoe contact forces or robot perception.

## Performance

Ablation uses the same 30 people, seed 42, GPU, 1920x1080 overview, segmented traffic and 1/30 s simulation step. Each throughput run warms for 30 wall seconds and measures 120 wall seconds. Baseline/full, no encoder, no CPU readback, and no render products are followed by restored full optimized mode. The no-product branch retains Replicator stepping for a closer scheduling comparison and logs actual app update counts; differences must be disclosed.

Throughput comparisons disable Tracy. A separate shorter Tracy capture has native zones plus SimPeople command, Kit/render, supervisor, journal and RGB/encoder ranges. Existing foreign GPU workloads are sampled and remain a confounder, not a reason to terminate user applications.

Optimizations cache native joint indices and shared per-frame poses, use a spatial broad phase before the unchanged exact root overlap criteria, and avoid reclassifying unchanged dynamic obstacle bounds. RGB encoding uses a bounded queue with frame identities, queue depth, submission waits, explicit stall failure and frame-count reconciliation. It does not silently drop frames.

## Protocol

Session IDs differ from resettable episode IDs. One logical controller owns session writes; readers remain available and takeover requires the current generation. Active runtime tasks persist through takeover. This is loopback client coordination, not network authentication.

Batch operations return individual outcomes and retain top-level request idempotency. Selection supports IDs, group, role and a planar region. Summary pages and bounded incremental events avoid sending all bones to an agent on every poll. The durable event journal remains complete. A minimal versioned scene handoff schema records navigation, units, locations and the managed namespace for future SimScene integration.

Seated entry and holding use different checks. A broad holding tolerance could temporarily match a native entry keyframe and start the hold clock too early; subsequent native settling then triggered an alignment failure. Entry now additionally waits for the actual Hips effector to be within 0.04 m before the existing stable interval. Holding geometry, speed and sustained-deviation thresholds remain unchanged.

The corridor profile builds local NavMesh edges on demand and caches only verified connections. It does not precompute every long path from the initial actor to every grid node; the open-floor twelve-rig test exposed that startup stall. The segmented comparison retains its prior eager graph.

The first render-only experiment retained a render product without an active RGB graph, changing app-update scheduling. It is retained as a diagnostic lower bound rather than an isolated CPU-copy measurement. The corrected profile attaches a GPU RGB annotator while avoiding any readback, and requires a separate native check. The initial Tracy capture also contained buffered startup and lacked the intended custom ranges; its unfiltered totals are not steady-state attribution. Corrected tracing uses an explicitly acquired Tracy interface.


The first 50-person continuous profile failed its functional gate at 274.8 simulated seconds. Full-journey claims caused avoidable contention; a timed-out distant seat approach then unnecessarily tried to return to the chair's egress and failed cleanup. The retained failure has 50 moving participants but zero minimum completed cycles and one suspended actor. Large-crowd corridors now reserve bounded 12 m walk / 18 m jog prefixes with native braking and preserve unvisited via goals. A stopped standing actor outside the entire configured egress envelope plus the existing arrival tolerance can release a cancelled approach in place. Near-chair transitions still use native egress. Both changes require new native acceptance; the original run remains failed.

The distant-seat cleanup also waits for actual native speed below the existing 0.15 m/s stop criterion before choosing an egress target. Idle action identity alone can precede physical deceleration. A dedicated native failure exposed this ordering error; the corrected near/far cleanup decisions are tested independently.

`--cpu-threads` defaults to the original eight workers. `--renderer-profile ampere_retrace` is an explicit, optional RT2 retrace setting of 0.1, with the image-accuracy tradeoff described by NVIDIA. Neither changes by default; throughput and actual runtime settings are recorded for their separate controlled trials.
