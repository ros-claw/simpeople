"""Collect versioned gates without marking pending or external-auth work passed."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(path):
 p=ROOT/path;return json.loads(p.read_text()) if p.exists() else None
cases={'motion':'opt1031-motion-CD-lazy-03','gait':'opt1031-gait-corridor-12-02','seat':'opt1031-seat-calibrated-v3-12-02','codex':'opt1031-host-codex-02',
       'population50_first_attempt':'opt1031-regression50-seed17-01','population50_bounded_attempt':'opt1031-regression50-seed17-02','population50':'opt1031-regression50-seed17-03','cleanup':'opt1031-cleanup-corridor-13-02'}
gates={}
for key,file in [('motion','motion_acceptance.json'),('gait','gait_pool_acceptance.json'),('seat','seat_acceptance.json'),('codex','host_acceptance.json')]:
 p='runs/'+cases[key]+'/'+file;data=read(p);gates[key]={'passed':data.get('passed') if data else None,'evidence':p}
q=read('runs/'+cases['seat']+'/seat_quality.json');gates['seat_vertices']={'passed':bool(q and q['rigs_sampled']==12 and q['rigs_without_vertex_penetration']==12 and q['fine_all_available']),'evidence':'runs/'+cases['seat']+'/seat_quality.json'}
claude=read('reports/optimization_1031_claude_status.json');gates['claude_package_and_mcp']={'passed':bool(claude and any('Connected' in x for x in claude['mcp_healthcheck'])),'evidence':'reports/optimization_1031_claude_status.json'}
gates['claude_natural_language']={'passed':None,'status':'requires local host login; not executed','evidence':'reports/optimization_1031_claude_status.json'}
for key in ['population50_first_attempt','population50_bounded_attempt','population50']:
 summary=read('runs/'+cases[key]+'/acceptance_summary.json');metrics=read('runs/'+cases[key]+'/metrics.json')
 gates[key]={'passed':summary.get('functional_population_gate_passed') if summary else None,'status':'closed' if metrics else 'pending native run','evidence':'runs/'+cases[key]+'/acceptance_summary.json'}
path='runs/'+cases['cleanup']+'/cleanup_acceptance.json';data=read(path)
gates['cleanup_and_bounded_vias']={'passed':data.get('passed') if data else None,'evidence':path}
performance_final=[]
for capture in ['full','no_encode','render_only','trace']:
 name='opt1031-final30-'+capture.replace('_','-')+'-01';metrics=read('runs/'+name+'/metrics.json')
 if metrics:performance_final.append({'run_id':name,'capture_profile':capture,'config':read('runs/'+name+'/config.json'),'metrics':metrics,'recording':read('runs/'+name+'/recording_metrics.json')})
full_path='runs/opt1031-final30-full-02/metrics.json' if read('runs/opt1031-final30-full-02/metrics.json') else 'runs/opt1031-final30-full-01/metrics.json'
full=read(full_path)
gates['performance30_realtime']={'passed':bool(full['rtf']>=.8 and full['measured_updates_per_wall_second']>=24) if full else None,'evidence':full_path}
interactive_path='reports/optimization_1031_interactive_performance.json';interactive=read(interactive_path)
gates['interactive10_realtime']={'passed':interactive.get('realtime_24_updates_and_rtf_08') if interactive else None,'evidence':interactive_path,'scope':'720p throughput sample, not a 600-second population gate'}
trace=read('runs/opt1031-final30-trace-04/profile_summary.json');trace_meta=read('runs/opt1031-final30-trace-04/trace_metadata.json')
gates['tracy_steady_window']={'passed':bool(trace.get('main_thread_phase_wall_fraction') and .8<=trace.get('main_thread_phase_coverage',0)<=1.05 and trace_meta and trace_meta.get('listener_verified_pid')==trace_meta.get('pid')) if trace else None,'evidence':'runs/opt1031-final30-trace-04/profile_summary.json'}
framing_path='runs/'+cases['population50']+'/framing_audit.json';framing=read(framing_path)
gates['population50_initial_framing']={'passed':framing.get('all_initial_actor_extents_inside') if framing else None,'evidence':framing_path}
for key,path in [('mcp_reconnect_ownership','runs/'+cases['population50_bounded_attempt']+'/mcp_ownership_acceptance.json'),
                 ('launcher_native_exit_status','reports/optimization_1031_launcher_validation.json')]:
 data=read(path);gates[key]={'passed':data.get('passed') if data else None,'evidence':path}
paths=[g['evidence'] for g in gates.values()];paths+=['configs/quality_catalog.json','reports/optimization_1031_performance.json']
inputs=[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in dict.fromkeys(paths) if (ROOT/p).is_file()]
population_failures=[{k:t.get(k) for k in ['task_id','actor_id','status','step_index','accepted_sim_time','finished_sim_time','error']}
                     for t in (read('runs/'+cases['population50']+'/tasks.json') or []) if t['status']=='failed']
result={'scope':'1031 quality/product iteration; historical v0.1 population gates are separate','source_commit':subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip(),'gates':gates,'input_hashes':inputs,'all_requested_targets_met':False,'limits':['Claude natural-language trials need login','24 actual wall-clock updates/s and RTF 0.8 not achieved','no exact whole-body contact or arbitrary-rig certification']}
(ROOT/'reports/optimization_1031_gates.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
(ROOT/'reports/optimization_1031_results.json').write_text(json.dumps({'cases':cases,'gates':gates,'performance':read('reports/optimization_1031_performance.json'),'performance_final':performance_final,
 'optional_performance':read('reports/optimization_1031_optional_performance.json'),
 'controlled_profile_followup':read('reports/optimization_1031_final_performance.json'),'interactive_performance':interactive,'population50_failures':population_failures,'claude':claude},ensure_ascii=False,indent=2));print(json.dumps(gates,ensure_ascii=False,indent=2))
