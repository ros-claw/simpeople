"""Capture one real production take; only Codex supplies the pivotal retarget."""
import argparse,json,os,subprocess,time,shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PROMPT='把橙衣巡视员派到东侧 B1 复检位，把蓝衣巡视员派到 B2。长椅旁那位继续等，其他人照常。'
p=argparse.ArgumentParser();p.add_argument('--phase',choices=['technical','director','master'],required=True)
p.add_argument('--run-id',required=True);p.add_argument('--gpu',type=int,default=0);p.add_argument('--port',type=int,default=8790)
p.add_argument('--lively',action='store_true',help='32 people and locally accepted native custom clips')
a=p.parse_args();directory=ROOT/'runs'/a.run_id
assert not directory.exists(),'preserve existing takes'
logs=ROOT/'.runtime/shift_change';logs.mkdir(exist_ok=True)
command=['python3','-m','simpeople.tools.cli','run','--scenario','industrial_life','--people',('1' if a.phase=='technical' else ('32' if a.lively else '24')),
         '--seed','31','--traffic-profile','corridor','--gpu',str(a.gpu),'--port',str(a.port),'--width','1920','--height','1080',
         '--duration',{'technical':'35','director':'28','master':'95'}[a.phase],'--run-id',a.run_id,
         '--cinematic-config',str(ROOT/'configs'/('shift_change_'+a.phase+('_lively' if a.lively else '')+'.json')),'--quality-audit']
if a.lively:command.extend(['--custom-actions'])
with (logs/(a.run_id+'.log')).open('w') as native_log:
 process=subprocess.Popen(command,cwd=ROOT,stdout=native_log,stderr=subprocess.STDOUT)
 host=None;out=err=None
 while process.poll() is None:
  ready=directory/'cinematic_command_ready.json'
  if ready.exists() and host is None:
   context=('这是用户授权的影片实际改令。上面这句话原样执行，使用 SimPeople MCP。人物 ID：橙衣 patrol_orange，蓝衣 patrol_blue，长椅旁等候者 bench_waiter。'
            'B1/B2 是场景语义锚点。先读会话并申请写控制权，核对这三人。仿真正在等待本次指令；'
            '必须先提交两人的新任务，再开始轮询。优先用 people_crowd 的 operation=run_activity 和 items 一次批量提交，'
            '每人 steps 先 move_to 到其 B 锚点，再 look_at 对应的 B1_device 或 B2_device，停稳后面向设备。两人提交完运行时会自动恢复仿真。提交后确认两人开始移动即可，最终到达由原生逐帧日志核对。'
            '不要改动其他人物，不要创建人物，不要控制暂停、镜头、录制或重置，不要修改文件，不要调用其他插件。')
   prompt=PROMPT+'\n\n'+context
   (directory/'codex_prompt.txt').write_text(prompt)
   (directory/'codex_host_manifest.json').write_text(json.dumps({'version':subprocess.run(['codex','--version'],capture_output=True,text=True,check=True).stdout.strip(),
      'prompt_wall_time':time.time(),'exact_user_command':PROMPT,'filesystem':'read-only','policy':'scoped approval for this local SimPeople server only','model':'host default'},ensure_ascii=False,indent=2))
   workspace=logs/'host-workspace';workspace.mkdir(exist_ok=True)
   endpoint='http://127.0.0.1:'+str(a.port)
   host_path=str(ROOT/'.venv-controller/bin')+os.pathsep+os.environ['PATH']
   mcp_command=shutil.which('simpeople',path=host_path)
   if not mcp_command:raise RuntimeError('SimPeople executable missing for the real host')
   cmd=['codex','exec','--json','--ephemeral','--skip-git-repo-check','--disable','apps','-s','read-only','-C',str(workspace),
        '-c','mcp_optional_startup_grace_ms=0','-c','mcp_servers.simpeople.enabled=true','-c','mcp_servers.simpeople.required=true',
        '-c','mcp_servers.simpeople.startup_timeout_sec=60','-c','mcp_servers.simpeople.tool_timeout_sec=60',
        '-c','mcp_servers.simpeople.command='+json.dumps(mcp_command),'-c','mcp_servers.simpeople.args=["mcp"]',
        '-c','mcp_servers.simpeople.cwd='+json.dumps(str(ROOT)),
        '-c','mcp_servers.simpeople.default_tools_approval_mode="approve"',
        '-c','mcp_servers.simpeople.env={SIMPEOPLE_ENDPOINT="'+endpoint+'",SIMPEOPLE_CONTROLLER_ID="film-codex"}',
        '-o',str(directory/'codex_final.txt'),prompt]
   env=os.environ.copy();env['PATH']=host_path
   out=(directory/'codex_session.jsonl').open('w');err=(directory/'codex_stderr.txt').open('w')
   host=subprocess.Popen(cmd,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err)
  time.sleep(1)
 code=process.returncode
 if host:
  try:host_code=host.wait(timeout=180)
  except subprocess.TimeoutExpired:host.terminate();host_code=124
  out.close();err.close()
 else:host_code=None
count=sum(1 for _ in (directory/'cinematic_frames.jsonl').open()) if (directory/'cinematic_frames.jsonl').exists() else 0
expected={'technical':900,'director':720,'master':2700}[a.phase]
if count!=expected and code==0:code=2
if a.phase!='technical' and host is None and code==0:code=3
result={'run_id':a.run_id,'phase':a.phase,'native_exit_code':code,'host_exit_code':host_code,'source_frames':count,'expected_frames':expected}
(logs/(a.run_id+'-completion.json')).write_text(json.dumps(result,indent=2));print(json.dumps(result))
raise SystemExit(code or (host_code or 0))
