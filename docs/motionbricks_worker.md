# MotionBricks local asset worker

This optional process produces assets. It does not own a live actor and imports no
Kit modules. Behavior remains the sole native pose writer. NumPy is optional in
the protocol package; TensorRT, Warp and MotionBricks belong in a separate Python
3.12 environment, never in Isaac's Python environment.

The qualified upstream is `NVlabs/motionbricks` commit
`54fc563aeaaf819a753d72cc9fdc6713989cdd43`. Start from that checkout and its
`uv.lock` (`uv sync --locked --python 3.12`). The exported dependency versions are
also recorded in `workers/motionbricks/requirements.lock.txt`. Use the upstream
asset download workflow to obtain the FP32 SOMA model and local evaluation
motions. Source code, model weights and evaluation clips have different license
terms; this repository does not redistribute the latter assets.

The worker verifies the upstream commit, model content hash, full rig hash and
source skeleton hash before inference. It uses FP32, batch size 1, TF32 disabled.
`model_provenance.json` and each worker artifact record installed package versions,
upstream lock hash, backend source hash and cold initialization time.

## Reproduce the coordinate and generation gates

The commands below require local assets and a GPU; paths are configurable. Every
output directory/run ID must be new. Existing failed evidence is retained.

```bash
.runtime/motionbricks/venv/bin/python workers/motionbricks/export_rig.py \
  --upstream .runtime/motionbricks/upstream --output .runtime/motionbricks/fixtures_new

.runtime/motionbricks/venv/bin/python workers/motionbricks/probe_model.py \
  --upstream .runtime/motionbricks/upstream \
  --rig-dir .runtime/motionbricks/fixtures_new --output runs/model20_new

/data/omniverse/isaac-sim-6.2.0/python.sh scripts/probe_motionbricks_soma.py \
  --run-id soma_known_new --data-dir .runtime/motionbricks/fixtures_new --gpu 3

/data/omniverse/isaac-sim-6.2.0/python.sh scripts/probe_motionbricks_soma.py \
  --run-id soma_generated_new --data-dir runs/model20_new --gpu 3
```

The full SOMA rig has 77 joints; the model uses an explicitly named subset of 30.
Projection uses world forward kinematics and the nearest modeled ancestor, so
intervening unmodeled joints are preserved. Expansion uses reference transforms
for extra joints. The protocol uses metres, Z up, XYZ + XYZW; the root is in world
space and all child transforms are joint-local. The original source is Y up in
centimetres. Only the root receives the axis conversion; no second basis rotation
is applied to child-local transforms.

The independent SOMA probe has no Behavior API. It renders synchronously and
reads actual `UsdSkel` world transforms back from Isaac at each simulation sample.
A separate native witness walks during replay. This verifies coordinate and USD
replay conversion; it does not certify native Human retargeting or physical contact.

## Worker protocol

```bash
.runtime/motionbricks/venv/bin/python workers/motionbricks/worker.py \
  --upstream .runtime/motionbricks/upstream \
  --rig .runtime/motionbricks/fixtures_new/rig.json \
  --endpoint .runtime/motionbricks/worker.sock \
  --workspace .runtime/motionbricks/artifacts --device cuda:3
```

The private Unix socket accepts only `ping`, `prepare`, `status`, `cancel`.
`MotionBricksProvider` is a standard-library client. There is no remote code
execution, pose-apply operation or model installation inside Kit.

`prepare` requires the strict MotionSpec schema, a matching rig revision, four
30 Hz context samples, and one to four target poses. Predicted contexts are
rejected. `executed_history` additionally requires session, episode, actor,
actor-instance, actor control epoch, task and context digest. These are identity
fields; a caller declaring executed history is not proof of a validated PoseBridge.

Duplicate request IDs with identical bodies return the same job; changed bodies
are rejected. Admission and history are bounded. Worker-instance fencing rejects
receipts after a restart. Active cancellation retains its admission slot until
inference returns, discards the late result, and explicitly reports
`actor_stop_verified: false`. Queued cancellation does not run the model. Native
actor cancellation is a separate lifecycle.

Results retain raw network features/tokens, raw decoded poses, corrected poses,
foot-contact channels, hashes and provenance. `validate_artifact` checks owned
paths, file hashes, bounded archive sizes, finite/unit transforms, decoded frame
count and token consistency. It cannot certify motion quality or actor execution.
Both native/retarget verification flags from this worker must remain false.

```bash
PYTHONPATH=src python3 scripts/probe_motion_worker.py \
  --run-id worker_new --python .runtime/motionbricks/venv/bin/python \
  --upstream .runtime/motionbricks/upstream \
  --fixtures .runtime/motionbricks/fixtures_new --model-cases runs/model20_new
```

This probe launches only its own workers and records actual official-model IPC,
duplicate/conflict, overload, cancellation/late discard, disconnect and restart.
It injects a documented 0.5 second publication delay to expose cancellation races;
its timings are not performance benchmarks. Native application, canonical entry,
live reload, segment queues and crowd generation are separate gates.

The optional `people_motion` MCP tool uses `SIMPEOPLE_MOTION_ENDPOINT` to locate
this private socket. Its strict operations are `prepare`, `status`, `cancel`.
Without that environment variable it reports unsupported while existing native
tools keep their current bridge. Request IDs are scoped to the MCP client;
status/cancel require the returned worker instance. This tool neither acquires
native actor control nor applies any result. A worker's binding fields never
grant permission to play a clip. `probe_motion_worker.py --mcp` additionally
exercises actual stdio discovery, duplicate preparation, polling and cancellation
against the real engine; it is not a natural-language host benchmark.
