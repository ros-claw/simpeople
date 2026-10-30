"""Sequential controlled wall-clock ablation; no profiler in throughput runs."""
import argparse,json,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--after-run');p.add_argument('--prefix',default='opt1031-perf30');a=p.parse_args()
root=Path(__file__).resolve().parents[1]
if a.after_run:
 d=root/'runs'/a.after_run
 while not (d/'metrics.json').exists():time.sleep(2)
 pid=json.loads((d/'ready.json').read_text())['pid']
 while Path(f'/proc/{pid}').exists():time.sleep(1)
results=[]
for index,(capture,profile,tracy) in enumerate([('full','baseline',False),('no_encode','baseline',False),('render_only','baseline',False),('none','baseline',False),('full','optimized',False),('full','optimized',True)]):
 run=f'{a.prefix}-{index+1:02d}-{capture.replace("_","-")}'
 cmd=['python3','-m','simpeople.tools.cli','run','--scenario','industrial_life','--people','30','--seed','42','--gpu','0','--port','8780','--width','1920','--height','1080','--traffic-profile','segmented','--capture-profile',capture,'--performance-profile',profile,'--duration','3600','--warmup-wall-s','30','--measure-wall-s',('20' if tracy else '120'),'--run-id',run]
 if tracy:cmd.append('--tracy')
 log=root/'.runtime/optimization_1031'/(run+'.log')
 with log.open('w') as f:r=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT)
 metrics_path=root/'runs'/run/'metrics.json'
 results.append({'run_id':run,'returncode':r.returncode,'capture':capture,'performance_profile':profile,'tracy':tracy,'metrics':json.loads(metrics_path.read_text()) if metrics_path.exists() else None})
 (root/'reports/optimization_1031_performance.json').write_text(json.dumps(results,indent=2))
 if r.returncode:raise SystemExit('run failed; inspect '+str(log))
print(json.dumps([{'run_id':r['run_id'],'rtf':r['metrics']['rtf']} for r in results],indent=2))
