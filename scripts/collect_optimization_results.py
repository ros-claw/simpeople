"""Collect versioned gates without marking pending or external-auth work passed."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(path):
 p=ROOT/path;return json.loads(p.read_text()) if p.exists() else None
cases={'motion':'opt1031-motion-CD-lazy-03','gait':'opt1031-gait-corridor-12-02','seat':'opt1031-seat-calibrated-v3-12-02','codex':'opt1031-host-codex-02','population50':'opt1031-regression50-seed17-01'}
gates={}
for key,file in [('motion','motion_acceptance.json'),('gait','gait_pool_acceptance.json'),('seat','seat_acceptance.json'),('codex','host_acceptance.json')]:
 p='runs/'+cases[key]+'/'+file;data=read(p);gates[key]={'passed':data.get('passed') if data else None,'evidence':p}
q=read('runs/'+cases['seat']+'/seat_quality.json');gates['seat_vertices']={'passed':bool(q and q['rigs_sampled']==12 and q['rigs_without_vertex_penetration']==12 and q['fine_all_available']),'evidence':'runs/'+cases['seat']+'/seat_quality.json'}
claude=read('reports/optimization_1031_claude_status.json');gates['claude_package_and_mcp']={'passed':bool(claude and any('Connected' in x for x in claude['mcp_healthcheck'])),'evidence':'reports/optimization_1031_claude_status.json'}
gates['claude_natural_language']={'passed':None,'status':'requires local host login; not executed','evidence':'reports/optimization_1031_claude_status.json'}
summary=read('runs/'+cases['population50']+'/acceptance_summary.json');metrics=read('runs/'+cases['population50']+'/metrics.json')
gates['population50']={'passed':summary.get('functional_population_gate_passed') if summary else None,'status':'closed' if metrics else 'running','evidence':'runs/'+cases['population50']+'/acceptance_summary.json'}
paths=[g['evidence'] for g in gates.values()];paths+=['configs/quality_catalog.json','reports/optimization_1031_performance.json']
inputs=[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in dict.fromkeys(paths) if (ROOT/p).is_file()]
result={'scope':'1031 quality/product iteration; historical v0.1 population gates are separate','source_commit':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip(),'gates':gates,'input_hashes':inputs,'all_requested_targets_met':False,'limits':['Claude natural-language trials need login','24 actual wall-clock updates/s and RTF 0.8 not achieved','no exact whole-body contact or arbitrary-rig certification']}
(ROOT/'reports/optimization_1031_gates.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
(ROOT/'reports/optimization_1031_results.json').write_text(json.dumps({'cases':cases,'gates':gates,'performance':read('reports/optimization_1031_performance.json'),'claude':claude},ensure_ascii=False,indent=2));print(json.dumps(gates,ensure_ascii=False,indent=2))
