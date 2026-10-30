# SimPeople development

Use the configured Isaac installation; protocol tests do not establish native animation acceptance. Keep Kit imports in the native adapter, entry scripts and extension. All USD/Behavior mutations run on the Kit main thread. Preserve request idempotency, session/episode/controller generations, simulation-clock waits, cancellation settlement and resource cleanup. Do not teleport roots or add another bone writer to conceal failures.

Run `PYTHONPATH=src python3 -m pytest -q tests`. Native acceptance also requires actual trajectories and continuous footage. Read `reports/REFERENCE_ACCEPTANCE.md`, `reports/OPTIMIZATION_20261031.md` and `docs/acceptance_criteria.md` before changing claims. Keep failed runs intact. Source inputs are frozen under each run's source_snapshot. Assets, caches, videos, runtime logs and credentials stay outside Git. Do not stop unrelated Isaac processes.
