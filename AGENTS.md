# SimPeople development

- Target the existing Isaac Sim 6.2 installation; do not substitute a different runtime to claim acceptance.
- Keep Kit imports in the native adapter, Kit entry scripts and extension. Protocol, CLI and tests run in system Python.
- All USD/Behavior mutation happens on the Kit main thread. HTTP workers only enqueue data. Never add remote Python evaluation.
- One controller owns each actor. Native tasks, actual runtime transforms and journal events decide outcomes; an accepted request is not completion.
- Preserve request idempotency, episode/control epochs, simulation-clock waits, cancellation settlement and resource cleanup.
- Test ordinary changes with `PYTHONPATH=src python3 -m pytest -q tests`. Real animation acceptance additionally requires Kit trajectories and continuous footage.
- Read `reports/phase_gates.json`, `reports/REFERENCE_ACCEPTANCE.md` and `docs/acceptance_criteria.md` before changing capability claims. Do not rewrite failed runs as passed.
- GPU Warp RGB readback failed on nonzero GPUs in this local RC build; default to the verified CPU path until cross-GPU validation proves otherwise. Use synchronized snapshots to prevent previous-camera images from being mislabeled.
- Run inputs are frozen under each new run's `source_snapshot`. Keep videos, caches, models and textures outside version control. Reference existing user assets without modifying their source USD files.
- Do not stop unrelated Isaac processes. Ports, GPU index and installation path are configurable.
