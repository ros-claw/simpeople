"""Advance an authorized long acceptance run only after real evidence passes."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from summarize_run import summarize
p=argparse.ArgumentParser();p.add_argument('--completed-run',required=True);p.add_argument('--phase',required=True)
p.add_argument('--next-run',required=True);p.add_argument('--next-people',type=int,required=True);p.add_argument('--next-duration',type=float,required=True)
p.add_argument('--next-seed',type=int,default=42);p.add_argument('--gpu',type=int,default=3);p.add_argument('--port',type=int,default=8768)
a=p.parse_args();directory=ROOT/'runs'/a.completed_run;deadline=time.monotonic()+12*3600
status=ROOT/'reports/continuation_status.json'
status.write_text(json.dumps({'waiting_for':a.completed_run,'next_run':a.next_run,'state':'waiting'},indent=2))
while time.monotonic()<deadline:
 if all((directory/n).exists() for n in ['completion.json','metrics.json','tasks.json']):
  ready=json.loads((directory/'ready.json').read_text())
  try:active=b'kit_main.py' in Path(f'/proc/{ready["pid"]}/cmdline').read_bytes()
  except FileNotFoundError:active=False
  if not active:break
 time.sleep(2)
else:raise TimeoutError('acceptance evidence did not close within 12 wall hours')
result=summarize(directory)
if not (directory/'framing_audit.json').exists():
 subprocess.run([sys.executable,str(ROOT/'scripts/check_framing.py'),str(directory)],check=True)
framing=json.loads((directory/'framing_audit.json').read_text())
if not result['functional_population_gate_passed'] or not framing['all_initial_actor_extents_inside']:
 status.write_text(json.dumps({'state':'gate_failed','run_id':a.completed_run,'summary':str(directory/'acceptance_summary.json')},indent=2))
 raise SystemExit('Gate failed; next population was not launched.')
gates_path=ROOT/'reports/phase_gates.json';gates=json.loads(gates_path.read_text())
gates[a.phase]={'passed':True,'run_id':a.completed_run,'scope':f"{result['richness']['instances']} people, {result['performance']['sim_elapsed_s']} sim seconds; every actor completed >=1 role cycle",
 'summary':f'runs/{a.completed_run}/acceptance_summary.json','framing':f'runs/{a.completed_run}/framing_audit.json',
 'performance_target_met':result['performance_target_met'],'rtf':result['performance']['rtf']}
gates_path.write_text(json.dumps(gates,ensure_ascii=False,indent=2)+'\n')
status.write_text(json.dumps({'state':'launching_next','passed_run':a.completed_run,'next_run':a.next_run},indent=2))
with (ROOT/'.runtime'/(a.next_run+'-driver.log')).open('w') as log:
 code=subprocess.call([sys.executable,'-m','simpeople.tools.cli','run','--scenario','industrial_life','--people',str(a.next_people),
                       '--duration',str(a.next_duration),'--seed',str(a.next_seed),'--gpu',str(a.gpu),'--port',str(a.port),'--run-id',a.next_run],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
status.write_text(json.dumps({'state':'next_run_closed','run_id':a.next_run,'exit_code':code},indent=2))
print(json.dumps({'passed_run':a.completed_run,'next_run':a.next_run,'exit_code':code}),flush=True)
