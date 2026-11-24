"""Conservative job ownership with one verified, Native-free CLI exception."""
import hashlib
import re
from pathlib import Path


def owned_job_id(argv, cwd, *, cpu_preflight_script=None, cpu_preflight_sha256=None):
    """Return a reserved runtime job ID, or None for an audited CPU preflight.

    Unknown executables with a reserved ID remain blockers. An exception needs
    the exact direct Python entry script, flag, path and approved source hash;
    a similar name or a stale source cannot authorize concurrent Native work.
    """
    run_ids = [argv[i+1] for i, arg in enumerate(argv[:-1]) if arg == '--run-id']
    run_ids.extend(arg.partition('=')[2] for arg in argv if arg.startswith('--run-id='))
    run_id = next((value for value in run_ids if re.match(r'^iter[0-9]{4}', value)), None)
    if run_id is None: return None
    if (len(run_ids) == 1 and cpu_preflight_script and cpu_preflight_sha256 and len(argv) > 1
            and Path(argv[0]).name in {'python', 'python3', 'python3.10', 'python3.11', 'python3.12'}
            and '--host-preflight-only' in argv):
        script = Path(argv[1])
        if not script.is_absolute(): script = Path(cwd)/script
        try:
            source = Path(cpu_preflight_script).resolve()
            if script.resolve() == source and hashlib.sha256(source.read_bytes()).hexdigest() == cpu_preflight_sha256:
                return None
        except OSError:
            pass
    return run_id
