import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

DEFAULT_ISAAC='/data/omniverse/isaac-sim-6.2.0'

def command(args):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=15)
        return {'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    except (OSError,subprocess.TimeoutExpired) as e:return {'error':str(e)}

def doctor(isaac_dir,output):
    directory=Path(isaac_dir).resolve();out=Path(output);out.mkdir(parents=True,exist_ok=True)
    extensions=[]
    for base in ['exts','extscache']:
        if (directory/base).exists():
            for p in (directory/base).iterdir():
                if any(n in p.name for n in ['omni.anim.','replicator.agent','behavior.tree','behavior_tree_gen']):
                    extensions.append({'id':p.name,'path':str(p),'status':'discovered'})
    disk=shutil.disk_usage(out)
    result={'isaac_dir':str(directory),'isaac_version':(directory/'VERSION').read_text().strip() if (directory/'VERSION').exists() else None,
            'launch_script_exists':(directory/'python.sh').exists(),'os':platform.platform(),
            'cpu':platform.processor(),'logical_cpu_count':os.cpu_count(),'controller_python':sys.version,
            'gpu':command(['nvidia-smi','--query-gpu=index,name,uuid,memory.total,memory.used,driver_version','--format=csv']),
            'memory':command(['free','-b']),'disk_free_bytes':disk.free,'display_present':bool(os.environ.get('DISPLAY')),
            'ffmpeg':shutil.which('ffmpeg'),'extensions':extensions,
            'runtime_probe':'reports/p0-native2/result.json; see loaded extension list and API docstrings alongside',
            'notes':['Read-only inspection; no upgrades performed.','Runtime loading and asset compatibility require Kit verification.']}
    (out/'environment_report.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    return result
