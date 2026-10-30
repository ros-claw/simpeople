"""OS resource sampling outside Kit's main thread. No stage access."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

class ResourceMonitor:
    def __init__(self,directory,gpu):
        self.stop_event=threading.Event();self.gpu=gpu
        self.file=(Path(directory)/'resources.jsonl').open('w',buffering=1)
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def run(self):
        import psutil
        process=psutil.Process();process.cpu_percent();children={}
        while not self.stop_event.is_set():
            sample={'wall_time':time.time(),'pid':os.getpid(),'process_rss_bytes':process.memory_info().rss,
                    'process_cpu_percent':process.cpu_percent(),'gpu_index':self.gpu}
            child_samples=[]
            for child in process.children():
                try:
                    tracked=children.setdefault(child.pid,child)
                    child_samples.append({'pid':child.pid,'name':tracked.name(),'cpu_percent':tracked.cpu_percent(),
                                          'threads':tracked.num_threads(),'rss_bytes':tracked.memory_info().rss})
                except psutil.Error:continue
            sample['child_processes']=child_samples
            try:
                result=subprocess.run(['nvidia-smi','-i',str(self.gpu),
                    '--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],
                    capture_output=True,text=True,timeout=3)
                if result.returncode==0:
                    memory,usage=[float(v.strip()) for v in result.stdout.strip().split(',')]
                    sample.update(gpu_total_used_mib=memory,gpu_total_utilization_percent=usage)
            except (OSError,ValueError,subprocess.TimeoutExpired) as e:sample['gpu_sample_error']=str(e)
            self.file.write(json.dumps(sample)+'\n')
            self.stop_event.wait(1)

    def close(self):
        self.stop_event.set();self.thread.join(timeout=5);self.file.close()
