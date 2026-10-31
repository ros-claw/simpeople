"""Summarize a steady suffix of a real Tracy trace; discard buffered startup.

csvexport's default comma output does not quote some C++ names. Use TSV. Native
zones overlap across threads; only disjoint SimPeople main-thread ranges may be
interpreted as a share of this selected wall-time window.
"""
import argparse,csv,json,re
from collections import defaultdict
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--window-s',type=float,default=8);a=p.parse_args();d=Path(a.directory)
file=d/'zone_events.tsv';end=0;start=None
with file.open() as f:
 for r in csv.DictReader(f,delimiter='\t'):
  if r['name'].startswith('SimPeople::'):
   t=int(r['ns_since_start']);end=max(end,t+int(r['exec_time_ns']));start=t if start is None else min(start,t)
if start is None:raise ValueError('SimPeople timeline ranges absent')
start=max(start,end-int(a.window_s*1e9));window=end-start;zones=defaultdict(lambda:{'total_ns':0,'counts':0,'threads':set()});phases=defaultdict(int)
with file.open() as f:
 for r in csv.DictReader(f,delimiter='\t'):
  t=int(r['ns_since_start']);duration=int(r['exec_time_ns']);clipped=max(0,min(t+duration,end)-max(t,start))
  if not clipped:continue
  key=(r['name'],r['src_file']);entry=zones[key];entry['total_ns']+=clipped;entry['counts']+=1;entry['threads'].add(r['thread'])
  if r['name'].startswith('SimPeople::'):phases[r['name']]+=clipped
rows=[{'name':k[0],'source_file':k[1],'aggregate_s':v['total_ns']/1e9,'counts':v['counts'],'threads':sorted(v['threads'])} for k,v in zones.items()];rows.sort(key=lambda v:v['aggregate_s'],reverse=True)
coverage=sum(phases.values())/window
if not .8<=coverage<=1.05:
 raise ValueError('manual phase scopes do not cover one disjoint main-thread window: '+str(coverage))
report={'window_start_ns':start,'window_end_ns':end,'window_s':window/1e9,'method':'last steady 8 seconds within SimPeople trace ranges; events clipped to window to exclude buffered startup',
 'main_thread_phase_coverage':coverage,
 'main_thread_phase_wall_fraction':{k:v/window for k,v in phases.items()},'top_zones':rows[:30],'groups':{},
 'limitations':['native aggregate time overlaps across zones/threads and is not a wall-time percentage','CSV contains CPU scopes; device execution time requires reviewing GPU lanes in the retained Tracy file','profiling run is excluded from throughput comparisons']}
for group,pattern in [('behavior','behavior|crowd|navigation'),('pose_skin','poseUpdate|animation|animgraph|blend|retarget|skinning|skeleton|skinmesh'),('fabric_usd','fabric|usd|hydra'),('wait','wait|synchron|fence')]:
 report['groups'][group]=[r for r in rows if re.search(pattern,r['name']+' '+r['source_file'],re.I)][:10]
(d/'profile_summary.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k in {'window_s','main_thread_phase_wall_fraction','limitations'}},indent=2))
for group,rows in report['groups'].items():print(group,[(r['name'],round(r['aggregate_s'],3)) for r in rows[:3]])
