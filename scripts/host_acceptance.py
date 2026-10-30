"""Real Codex CLI natural-language trials against a dedicated live Kit session.

No synthetic LLM transcripts. Scoped MCP approval applies only to this local
server during these already authorized tests; filesystem sandbox stays read-only.
"""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.tools.client import call
p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);a=p.parse_args();d=ROOT/'runs'/a.run_id
prompts=[
 '这是 SimPeople 真实宿主验收。请使用 SimPeople 插件安排一个人 codex_life（default 外观）从 seat_00 附近的 [7.5,-10,0] 出发，走到 [8.75,-10,0]，再坐 seat_00 休息 1 个仿真秒，起身离开并停稳。先检查当前会话、NavMesh 和动作能力，再申请写控制权。验证整段计划，提交后查询直到整段实际成功，报告 task_id。只修改这个测试人物，不重置场景，不修改文件，不调用其他插件。',
 '继续 SimPeople 真实验收。请批量创建 codex_g1、codex_g2、codex_g3 三个人，group 都为 codex_group，位置分别 [-17.5,-18.75,0]、[-13.75,-18.75,0]、[-10,-18.75,0]。先给三人安排等待 60 仿真秒，然后只把前两人改令为分别走到 [-17.5,-15,0]、[-13.75,-15,0]，走完停稳。第三个人继续原来的等待。使用批量接口和分页汇总，报告前两人的实际终态与第三人的原任务 ID。不要修改其他人或重置场景。',
 '继续 SimPeople 真实验收。让 codex_g1 朝 [-17.5,15,0] 行走，确认它确实开始移动后中途取消，查询到 cancelled 且停稳，再给同一个人物安排等待 1 个仿真秒，查询至 succeeded。请报告被取消任务与恢复后任务的 ID，其他人物保持原计划。只用 SimPeople MCP，不修改文件，不重置场景。'
]
(d/'host_prompts.json').write_text(json.dumps(prompts,ensure_ascii=False,indent=2));results=[]
(d/'host_manifest.json').write_text(json.dumps({'host':'Codex CLI','version':subprocess.run(['codex','--version'],capture_output=True,text=True,check=True).stdout.strip(),'plugin':'simpeople@ros-claw-simpeople 0.2.0','model_selection':'host default; no model override supplied','filesystem_sandbox':'read-only','mcp_approval':'scoped explicit local server approve override','runtime_run_id':a.run_id},indent=2))
env=os.environ.copy();env['PATH']=str(ROOT/'.venv-controller/bin')+os.pathsep+env['PATH'];env['SIMPEOPLE_ENDPOINT']='http://127.0.0.1:8780';env['SIMPEOPLE_CONTROLLER_ID']='qa-codex'
workspace=ROOT/'.runtime/optimization_1031/host-qa';workspace.mkdir(exist_ok=True)
base=['codex','exec','--json','--ephemeral','--skip-git-repo-check','--disable','apps','-s','read-only','-C',str(workspace),'-c','mcp_servers.simpeople.command="simpeople"','-c','mcp_servers.simpeople.args=["mcp"]','-c','mcp_servers.simpeople.default_tools_approval_mode="approve"','-c','mcp_servers.simpeople.env={SIMPEOPLE_ENDPOINT="http://127.0.0.1:8780",SIMPEOPLE_CONTROLLER_ID="qa-codex"}']
for i,prompt in enumerate(prompts):
 with (d/f'codex_task_{i+1}.jsonl').open('w') as out,(d/f'codex_task_{i+1}.stderr').open('w') as err:
  try:r=subprocess.run(base+['-o',str(d/f'codex_task_{i+1}_final.txt'),prompt],env=env,stdout=out,stderr=err,timeout=900);code=r.returncode
  except subprocess.TimeoutExpired:code=124
 state=call('people.get_state',endpoint=env['SIMPEOPLE_ENDPOINT']);(d/f'codex_task_{i+1}_native_state.json').write_text(json.dumps(state,indent=2))
 rows=[]
 for line in (d/f'codex_task_{i+1}.jsonl').read_text().splitlines():
  try:x=json.loads(line)
  except ValueError:continue
  item=x.get('item',{})
  if x.get('type')=='item.completed' and item.get('type')=='mcp_tool_call' and item.get('server')=='simpeople':rows.append(item)
 results.append({'task_number':i+1,'returncode':code,'mcp_tool_calls':len(rows),'tool_errors':sum(x.get('error') is not None or x.get('status')=='failed' for x in rows),'native_actor_count':len(state['actors'])})
 (d/'host_acceptance_progress.json').write_text(json.dumps(results,indent=2))
 if code:break
print(json.dumps(results,indent=2))
