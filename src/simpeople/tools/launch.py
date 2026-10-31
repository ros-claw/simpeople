"""Launch a dedicated Kit process, preserve its raw log and forward user stops."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys

def resolve_run_exit_code(directory,launcher_code):
    """Some Kit launchers swallow SystemExit; the native journal is decisive."""
    if launcher_code:return launcher_code
    directory=Path(directory)
    try:
        metrics=json.loads((directory/'metrics.json').read_text())
        code=metrics['exit_code']
        if isinstance(code,bool) or not isinstance(code,int):return 1
        if code:return code
        completion=json.loads((directory/'completion.json').read_text())
        code=completion['exit_code']
        if isinstance(code,bool) or not isinstance(code,int):return 1
        return code or int((directory/'error.txt').exists())
    except (OSError,ValueError,KeyError,TypeError):
        # A zero launcher status without closed native evidence is incomplete.
        return 1

def run_logged(command,root,run_id):
    root=Path(root);directory=root/'runs'/run_id
    if directory.exists():raise ValueError('run_id already exists: '+run_id)
    logs=root/'.runtime/launch_logs';logs.mkdir(parents=True,exist_ok=True)
    staging=logs/(run_id+'.log')
    process=subprocess.Popen(command,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    def forward(sig,_):
        if process.poll() is not None:return
        for name in ['ready.json','bootstrap.json']:
            try:
                pid=json.loads((directory/name).read_text())['pid']
                cmd=Path(f'/proc/{pid}/cmdline').read_bytes()
                if b'kit_main.py' in cmd and run_id.encode() in cmd:
                    os.kill(pid,sig);return
            except (OSError,ValueError,KeyError):pass
        os.killpg(process.pid,sig)
    old={s:signal.signal(s,forward) for s in [signal.SIGINT,signal.SIGTERM]}
    try:
        with staging.open('wb') as log:
            for line in process.stdout:
                log.write(line);log.flush()
                sys.stdout.buffer.write(line);sys.stdout.buffer.flush()
        launcher_code=process.wait()
        code=resolve_run_exit_code(directory,launcher_code)
        if code!=launcher_code:
            print(json.dumps({'run_id':run_id,'launcher_exit_code':launcher_code,
                'runtime_exit_code':code,'exit_status_source':'closed native evidence or incomplete-run failure'}),flush=True)
        return code
    finally:
        for s,handler in old.items():signal.signal(s,handler)
        if directory.exists() and staging.exists():shutil.copy2(staging,directory/'kit.log')
