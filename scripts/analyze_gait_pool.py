"""Retain per-rig support-proxy results for a closed twelve-character run."""
import argparse,json
from pathlib import Path
from analyze_gait_quality import audit
p=argparse.ArgumentParser();p.add_argument('directory');a=p.parse_args();d=Path(a.directory)
acceptance=json.loads((d/'gait_pool_acceptance.json').read_text());assert acceptance['passed']
folder=d/'gait_quality';folder.mkdir(exist_ok=True);results={}
for row in acceptance['results']:
 result=audit(d,row['actor_id']);(folder/(row['actor_id']+'.json')).write_text(json.dumps(result,indent=2))
 results[row['asset_id']]={'actor_id':row['actor_id'],**{k:result[k] for k in ['samples','contact_intervals','drift_median_m','drift_p95_m','native_task_count','root_changed_without_sim_time_samples']}}
(d/'gait_pool_quality.json').write_text(json.dumps({'rigs':results,'all_contacts_measured':all(x['contact_intervals']>0 for x in results.values()),'scope':'calibrated contact proxies; no force or universal no-slip certificate'},indent=2))
print(json.dumps(results,indent=2))
