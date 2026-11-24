"""Actual installed host -> MCP -> dedicated Isaac session, with native grading.

This is a product acceptance test, not a coding delegate. Hosts receive no
implementation task, shell permission or filesystem-writing task.
"""
import argparse,asyncio,hashlib,json,os,re,shutil,signal,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.core.command_benchmark import load_suite,grade,completed_calls,fixture_errors
from simpeople.tools.client import call


def dump(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def jsonl(path):
    if not path.exists():return []
    rows=[]
    for line in path.read_text().splitlines():
        try:rows.append(json.loads(line))
        except ValueError:continue  # A live writer may have a partial final line.
    return rows
def read_from(path,offset):
    with path.open() as f:f.seek(offset);return [json.loads(l) for l in f if l.endswith('\n')]


async def discover(env,path):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    async with stdio_client(StdioServerParameters(command=str(ROOT/'.venv-controller/bin/python'),args=['-m','simpeople.tools.mcp_server'],env=env)) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            await session.initialize();listing=await session.list_tools();dump(path,listing.model_dump(mode='json'))


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--runtime-run');p.add_argument('--host',choices=['codex','claude'],default='codex');p.add_argument('--host-binary');p.add_argument('--host-plugin-dir');p.add_argument('--host-preflight-only',action='store_true');p.add_argument('--cases',nargs='+');p.add_argument('--repetitions',type=int,choices=[1,2,3],default=3);p.add_argument('--formal',action='store_true');args=p.parse_args()
    if args.host=='codex' and (args.host_preflight_only or args.host_binary or args.host_plugin_dir):p.error('host preflight/binary/plugin-dir flags currently apply to Claude only')
    suite=load_suite(ROOT/'benchmarks/commands/commandbench_v1.json',ROOT/'schemas/command-case.schema.json')
    selected=[c for c in suite['cases'] if not args.cases or c['case_id'] in args.cases]
    if not selected or args.cases and set(args.cases)-{c['case_id'] for c in selected}:p.error('unknown case IDs')
    if any(c['split']=='holdout' for c in selected) and not args.formal and not args.host_preflight_only:p.error('holdouts require a formal frozen evaluation')
    if args.formal and (args.cases or args.repetitions!=3):p.error('formal evaluation requires the whole 20 x 3 matrix')
    out=ROOT/'runs'/args.run_id;out.mkdir(exist_ok=False);snap=out/'source_snapshot';snap.mkdir()
    for name in ['src','schemas','benchmarks/commands','plugins/codex','plugins/claude']:
        shutil.copytree(ROOT/name,snap/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (snap/'scripts').mkdir();shutil.copy2(__file__,snap/'scripts'/Path(__file__).name);shutil.copy2(ROOT/'scripts/analyze_host_acceptance.py',snap/'scripts/analyze_host_acceptance.py')
    dump(out/'source_manifest.json',{str(f.relative_to(snap)):sha(f) for f in sorted(snap.rglob('*')) if f.is_file()})
    suite=load_suite(snap/'benchmarks/commands/commandbench_v1.json',snap/'schemas/command-case.schema.json');selected=[c for c in suite['cases'] if c['case_id'] in {x['case_id'] for x in selected}]
    # Freeze evaluator code as well as cases before a single host attempt.
    sys.path.insert(0,str(snap/'src'))
    import importlib.util
    spec=importlib.util.spec_from_file_location('frozen_command_grader',snap/'src/simpeople/core/command_benchmark.py');grader=importlib.util.module_from_spec(spec);spec.loader.exec_module(grader)
    claude_api=claude_proof=None
    if args.host=='claude':
        spec=importlib.util.spec_from_file_location('frozen_claude_host',snap/'src/simpeople/tools/claude_benchmark.py');claude_api=importlib.util.module_from_spec(spec);spec.loader.exec_module(claude_api)
        claude_proof=claude_api.preflight(ROOT,args.host_binary,reference_root=snap/'plugins/claude',plugin_dir=args.host_plugin_dir)
        dump(out/'host_preflight.json',claude_proof)
        if args.host_preflight_only or not claude_proof['ready']:
            dump(out/'completed.json',{'harness_completed':False,'host_preflight_only':True,'host_preflight_passed':claude_proof['ready'],'attempts_started':0,'native_session_mutated':False})
            print('CLAUDE_HOST_PREFLIGHT',json.dumps(claude_proof,ensure_ascii=False),flush=True)
            return 0 if claude_proof['ready'] else 2
    if not args.runtime_run:p.error('--runtime-run is required for an actual matrix')
    runtime=ROOT/'runs'/args.runtime_run;ready=json.loads((runtime/'ready.json').read_text());endpoint=ready['endpoint']
    # A stale ready file is never evidence of a live measurement process.
    os.kill(ready['pid'],0);session=call('session_info',endpoint=endpoint)
    if session['scene_id']!=suite['scene']:raise ValueError('frozen scene does not match live runtime')
    if session.get('batch_contract',{}).get('version')!=2:raise ValueError('this matrix requires the versioned instance-bound batch contract; update the dedicated runtime first')
    if args.host=='codex':
        version=subprocess.check_output(['codex','--version'],text=True).strip();plugins=json.loads(subprocess.check_output(['codex','plugin','list','--json'],text=True));dump(out/'host_plugins.json',plugins)
        installed=next(x for x in plugins['installed'] if x['pluginId']=='simpeople@ros-claw-simpeople' and x['enabled'])
        plugin=Path(installed['source']['path']);plugin_mcp=json.loads((plugin/'mcp.json').read_text())['mcpServers']['simpeople']
        if plugin_mcp['command']!='simpeople' or plugin_mcp['args']!=['mcp']:raise ValueError('unexpected installed plugin launcher')
        resolved=json.loads(subprocess.check_output(['codex','mcp','get','simpeople','--json'],text=True))['transport'];cache=Path(resolved.get('env',{}).get('PLUGIN_ROOT') or resolved.get('cwd') or plugin).resolve()
        cached_files=[cache/n for n in ['plugin.json','mcp.json','.mcp.json','.codex-plugin/plugin.json','skills/simpeople/SKILL.md'] if (cache/n).is_file()]
        if not (cache/'skills/simpeople/SKILL.md').is_file():raise ValueError('installed plugin skill cache is missing')
        for f in cached_files:
            target=snap/'host_installed/codex'/f.relative_to(cache);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
        dump(out/'source_manifest.json',{str(f.relative_to(snap)):sha(f) for f in sorted(snap.rglob('*')) if f.is_file()})
        client=plugin_mcp.get('env',{}).get('SIMPEOPLE_CONTROLLER_ID','simpeople-codex')
        if session['controller_id'] not in {None,client}:raise ValueError('dedicated runtime is owned by another controller; refusing takeover')
        env=os.environ.copy();env.update(SIMPEOPLE_ENDPOINT=endpoint,SIMPEOPLE_CONTROLLER_ID=client,PYTHONPATH=str(snap/'src'),PATH=str(ROOT/'.venv-controller/bin')+os.pathsep+env['PATH']);env.pop('SIMPEOPLE_MOTION_ENDPOINT',None)
        workspace=Path(tempfile.mkdtemp(prefix='simpeople-commandbench-'))
        (workspace/'AGENTS.md').write_text('This workspace is a SimPeople product acceptance session. Use the installed SimPeople plugin tools only. Do not run commands, edit files, browse, use another plugin, delegate, or reset the scene. Do not read implementation code or expected scoring predicates. Native tasks decide completion.\n')
        model=None;config=Path.home()/'.codex/config.toml'
        if config.is_file():
            match=re.search(r'^model\s*=\s*"([^"\n]+)"',config.read_text(),re.M)
            if match:model=match[1]
        base=['codex','exec','--json','--ephemeral','--skip-git-repo-check','--disable','apps','-s','read-only','-C',str(workspace),'--output-schema',str(snap/'benchmarks/commands/response.schema.json'),'-c','apps._default.enabled=false','-c','plugins."simpeople@ros-claw-simpeople".enabled=true','-c','plugins."simpeople@ros-claw-simpeople".mcp_servers.simpeople.default_tools_approval_mode="approve"']
        # Bind the effective installed server explicitly: ambient custom env need
        # not reach a plugin-launched MCP process. Approval is local-server scoped.
        mcp_env={k:env[k] for k in ['SIMPEOPLE_ENDPOINT','SIMPEOPLE_CONTROLLER_ID','PYTHONPATH','PATH']}
        # 0.168 validates an explicitly overridden server as a complete transport;
        # env/approval alone is rejected before plugin expansion. Mirror the
        # installed launcher and declare this compatibility binding in the report.
        base+=['-c','mcp_servers.simpeople.command='+json.dumps(plugin_mcp['command']),'-c','mcp_servers.simpeople.args='+json.dumps(plugin_mcp['args']),'-c','mcp_servers.simpeople.default_tools_approval_mode="approve"','-c','mcp_servers.simpeople.env={'+','.join(k+'='+json.dumps(v) for k,v in mcp_env.items())+'}']
        base+=['--disable','multi_agent','--disable','multi_agent_v2']
        for other in plugins['installed']:
            if other['pluginId']!=installed['pluginId']:base+=['-c','plugins.'+json.dumps(other['pluginId'])+'.enabled=false']
        if model:base+=['-m',model]
        manifest={'host':'Codex CLI','host_version':version,'model':model or 'CLI builtin default (not exposed)','runtime_run_id':args.runtime_run,'runtime_pid':ready['pid'],'session_id':session['session_id'],'plugin':installed,'installed_plugin_hashes':{str(f.relative_to(plugin)):sha(f) for f in [plugin/'plugin.json',plugin/'mcp.json',plugin/'skills/simpeople/SKILL.md']},'code_source_manifest_sha256':sha(out/'source_manifest.json'),'cases_sha256':sha(snap/'benchmarks/commands/commandbench_v1.json'),'formal':args.formal,'repetitions':args.repetitions,'case_ids':[c['case_id'] for c in selected],'mcp_approval':'only the installed local SimPeople server approved for authorized tests','filesystem_sandbox':'read-only','model_policy':'freeze existing configured model; do not choose a different one','token_budget_enforcement':'reported usage checked after completion; tool/wall/simulation limits monitored while running','cost':None,'cost_note':'host CLI does not expose monetary costs; no price estimate','workspace':str(workspace)}
        manifest['installed_plugin_binding_mode']='installed plugin and skill enabled; complete effective MCP transport overridden per invocation for endpoint, frozen package path and scoped approval (0.168 compatibility). Not automatic default-endpoint discovery.'
        manifest['installed_cache_root']=str(cache);manifest['installed_cache_hashes']={str(f.relative_to(cache)):sha(f) for f in cached_files}
    else:
        spec=importlib.util.spec_from_file_location('frozen_claude_host',snap/'src/simpeople/tools/claude_benchmark.py');claude_api=importlib.util.module_from_spec(spec);spec.loader.exec_module(claude_api)
        dump(out/'host_preflight.json',claude_proof)
        prepared=claude_api.prepare(ROOT,out,snap,endpoint,session,claude_proof)
        client,env,workspace,base,manifest,cache,cached_files=[prepared[k] for k in ['client','env','workspace','base','manifest','cache','cached_files']]
        dump(out/'source_manifest.json',{str(f.relative_to(snap)):sha(f) for f in sorted(snap.rglob('*')) if f.is_file()})
        manifest.update(runtime_run_id=args.runtime_run,runtime_pid=ready['pid'],session_id=session['session_id'],formal=args.formal,repetitions=args.repetitions,case_ids=[c['case_id'] for c in selected],code_source_manifest_sha256=sha(out/'source_manifest.json'),cases_sha256=sha(snap/'benchmarks/commands/commandbench_v1.json'),mcp_approval='only the qualified local SimPeople plugin transport and Skill',cost=None)
    manifest['runtime_inputs']={name:sha(runtime/name) for name in ['manifest.json','environment.json','environment_report.json','runtime_settings.json'] if (runtime/name).is_file()}
    dump(out/'host_manifest.json',manifest);asyncio.run(discover(env,out/'mcp_tool_schema.json'))
    owner=client;counter=0;results=[]
    def rpc(method,params=None):
        nonlocal counter
        counter+=1;body=dict(params or {})
        if method not in {'session_info','preflight','inspect_scene','crowd_state','get_state','list_actions','list_interactions'}:body.update(controller_id=owner,request_id=f'fixture_{args.run_id}_{counter}')
        return call(method,body,endpoint)
    if session['controller_id'] is None:rpc('control_session',{'action':'acquire'})
    for repetition in range(1,args.repetitions+1):
        for case in selected:
            if any(sha(cache/name)!=h for name,h in manifest['installed_cache_hashes'].items()):raise RuntimeError('installed host package changed during the frozen matrix')
            if args.host=='claude' and sha(claude_proof['binary'])!=claude_proof['binary_sha256']:raise RuntimeError('Claude binary changed during the frozen matrix')
            trial=out/f'{case["case_id"]}_r{repetition}';trial.mkdir();dump(trial/'case.json',case)
            rpc('reset',{'episode_id':rpc('session_info')['episode_id']})
            setup=[]
            for actor in case['fixture']['actors']:
                setup.append({'actor_id':actor['actor_id'],'asset_id':actor['asset_id'],'spawn_anchor':actor['position_m'],'group':actor['group'],'role':actor['role']})
            setup.append({'actor_id':'witness','asset_id':'default','spawn_anchor':[18,16,0],'group':'witness','role':'witness'})
            spawned=rpc('batch',{'operation':'spawn','items':setup});dump(trial/'fixture_spawn.json',spawned)
            if spawned['rejected']:raise RuntimeError('fixture spawn rejected; do not count as a host attempt')
            deadline=time.monotonic()+300
            while True:
                state=rpc('get_state')
                if all(a['observation'].get('ready') for a in state['actors']):break
                if time.monotonic()>deadline:raise TimeoutError('native actors did not become ready')
                time.sleep(.2)
            initial_errors=grader.fixture_errors(case,state,'spawned');dump(trial/'spawned_state.json',state);dump(trial/'fixture_spawn_check.json',{'passed':not initial_errors,'errors':initial_errors})
            if initial_errors:raise RuntimeError('native fixture position mismatch before host execution; see fixture_spawn_check.json')
            for aid in ['a','b','c']:rpc('run_activity',{'actor_id':aid,'steps':[{'action':'sit','target':'seat_00','duration_s':300,'timeout_s':120}] if case['fixture'].get('seated_actor')==aid else [{'action':'wait','duration_s':3600,'timeout_s':3610}]})
            patrol=[s for _ in range(100) for s in [{'action':'move_to','target':[18,18,0],'timeout_s':60},{'action':'move_to','target':[18,16,0],'timeout_s':60},{'action':'wait','duration_s':2}]]
            rpc('run_activity',{'actor_id':'witness','steps':patrol})
            while True:
                state=rpc('get_state');actors={a['actor_id']:a for a in state['actors']}
                settled=all(actors[a]['task']['status']=='running' for a in ['a','b','c','witness'])
                if case['fixture'].get('seated_actor'):settled=settled and actors['a']['task']['step_phase']=='holding'
                if settled:break
                if time.monotonic()>deadline:raise TimeoutError('fixture activity did not settle')
                time.sleep(.2)
            initial_errors=grader.fixture_errors(case,state,'prepared');dump(trial/'fixture_prepared_check.json',{'passed':not initial_errors,'errors':initial_errors})
            if initial_errors:raise RuntimeError('prepared fixture does not match frozen initial state; no host attempt started')
            before=state;dump(trial/'before.json',before);dump(trial/'capabilities.json',{a:rpc('list_actions',{'actor_id':a}) for a in ['a','b','c']});dump(trial/'scene.json',rpc('inspect_scene'))
            event_offset=(runtime/'events.jsonl').stat().st_size;trajectory_offset=(runtime/'trajectories.jsonl').stat().st_size
            request_prefix=f'{args.run_id}_{trial.name}_'
            prompt=('每个 request_id 必须使用本次独立会话前缀 '+request_prefix+'，在此前缀后加操作序号；重试同一个请求才重用原 ID。\n请使用已安装的 SimPeople 插件完成以下实际控制任务。这不是编程任务，只能使用此插件 MCP，不运行 shell、不改文件、不写根或骨骼、不重置场景、不使用其他插件。先查询 session/info、preflight、目标人物实际动作能力，再申请写控制权。正常活动先 validate 完整计划；对明确要求测试部分失败的批次要逐项保留结果。所有写请求绑定读到的 session_id/episode_id；同一人物实例绑定 actor_instance_id。只修改指令中的人物，witness 必须继续原来的巡逻。其他人的长期等待不需要等完。按 task_id 节流查询直到真实终态；取消要等 physical_stop_verified=true。最多两次局部修复，不延长原截止。最终按响应 schema 报告真实 task IDs、拒绝类别和简短中文结果。status 描述所请求动作/能力的结果：服务关闭或能力不支持须用 rejected，即使诊断查询已完成；已受理任务失败用 failed，只有所请求能力实际完成才用 completed。仿真预算 '+str(case['budget']['sim_s'])+' 秒，MCP 调用预算 '+str(case['budget']['tool_calls'])+' 次。\n\n'+case['prompt'])
            if args.host=='claude':prompt='请先调用 Skill 加载 simpeople:simpeople，再执行以下实际控制任务。\n'+prompt
            (trial/'prompt.txt').write_text(prompt);started=time.monotonic();interrupted=None;last_print=started;stdout=trial/'host.jsonl';stderr=trial/'host.stderr';last=trial/'final.json'
            with stdout.open('w') as output,stderr.open('w') as errors:
                invocation=base+(['-o',str(last),prompt] if args.host=='codex' else [prompt])
                process=subprocess.Popen(invocation,env=env,cwd=str(workspace) if args.host=='claude' else None,stdin=subprocess.DEVNULL,stdout=output,stderr=errors,start_new_session=True)
                dump(trial/'process.json',{'pid':process.pid,'started_wall_time':time.time(),'argv':invocation,'runtime_pid':ready['pid']})
                print('HOST_STARTED',trial.name,process.pid,flush=True)
                try:
                    while process.poll() is None:
                        elapsed=time.monotonic()-started;observed=rpc('crowd_state',{'limit':1});raw=jsonl(stdout)
                        view=claude_api.normalize(raw,expected_plugin_root=snap/'host_installed/claude') if args.host=='claude' else None
                        if view is not None and manifest.get('actual_model') and view['model'] and view['model']!=manifest['actual_model']:view['issues'].append({'code':'ACTUAL_MODEL_CHANGED'})
                        observed_call_count=view['requested_mcp_calls'] if view is not None else len(completed_calls(raw))
                        if elapsed>case['budget']['wall_s']:interrupted='wall_budget'
                        elif observed['sim_time']-before['sim_time']>case['budget']['sim_s']:interrupted='simulation_budget'
                        elif observed_call_count>case['budget']['tool_calls']:interrupted='tool_budget'
                        elif view is not None and view['issues']:interrupted='host_protocol_error'
                        if interrupted:
                            os.killpg(process.pid,signal.SIGTERM);break
                        if time.monotonic()-last_print>20:print('HOST_LIVE',trial.name,process.pid,round(elapsed,1),observed_call_count,flush=True);last_print=time.monotonic()
                        time.sleep(1)
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=10)
                finally:
                    if process.poll() is None:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10)
            execution={'returncode':process.returncode,'interrupted':interrupted,'wall_s':time.monotonic()-started};dump(trial/'execution.json',execution)
            after=rpc('get_state');after_scene=rpc('inspect_scene');dump(trial/'after_scene.json',after_scene);after['resource_snapshot']={k:after_scene[k] for k in ['resources','queues']};dump(trial/'after.json',after);events=read_from(runtime/'events.jsonl',event_offset);trajectory=read_from(runtime/'trajectories.jsonl',trajectory_offset)
            dump(trial/'native_events.json',events)
            with (trial/'native_trajectory.jsonl').open('w') as f:
                for row in trajectory:f.write(json.dumps(row)+'\n')
            trace=jsonl(stdout);adapter=None
            if args.host=='claude':
                adapter=claude_api.normalize(trace,finalize=True,expected_plugin_root=snap/'host_installed/claude');trace=adapter.pop('trace');final=adapter['final']
                from jsonschema import Draft202012Validator
                schema=json.loads((snap/'benchmarks/commands/response.schema.json').read_text())
                if list(Draft202012Validator(schema).iter_errors(final)):adapter['issues'].append({'code':'FINAL_REPORT_SCHEMA_INVALID'})
                actual_model=adapter['model']
                if not actual_model:adapter['issues'].append({'code':'ACTUAL_MODEL_NOT_RECORDED'})
                elif manifest.get('actual_model') not in (None,actual_model):adapter['issues'].append({'code':'ACTUAL_MODEL_CHANGED'})
                else:
                    manifest.setdefault('configured_model',manifest['model']);manifest['actual_model']=manifest['model']=actual_model;dump(out/'host_manifest.json',manifest)
                adapter['valid']=not adapter['issues'];dump(trial/'host_adapter.json',adapter);dump(last,final)
                with (trial/'normalized_host.jsonl').open('w') as f:
                    for row in trace:f.write(json.dumps(row,ensure_ascii=False)+'\n')
            else:
                try:final=json.loads(last.read_text())
                except (OSError,ValueError):final={}
            result=grader.grade(case,before,after,events,trajectory,trace,final,execution)
            if adapter is not None:
                result['checks']['host_trace_protocol_valid']=adapter['valid'];result['passed']=all(result['checks'].values());result['host_adapter_issues']=adapter['issues'];result['host_reported_cost_usd']=adapter['total_cost_usd']
            result['repetition']=repetition;dump(trial/'result.json',result);results.append(result)
            dump(out/'progress.json',results);print('HOST_RESULT',case['case_id'],repetition,result['passed'],[k for k,v in result['checks'].items() if not v],flush=True)
            dump(out/'host_acceptance.json',grader.summarize(manifest,results))
            if adapter is not None and any(i['code']=='ACTUAL_MODEL_CHANGED' for i in adapter['issues']):raise RuntimeError('Claude actual model changed; frozen matrix stopped after retaining the failed attempt')
    dump(out/'completed.json',{'harness_completed':True,'formal':args.formal,'planned':len(selected)*args.repetitions,'attempts':len(results),'passed':sum(r['passed'] for r in results),'results':results,'no_claim_for_unrun_host':'Each host has its own matrix; results are not substituted across hosts.'})
    print('COMMANDBENCH_DONE',len(results),sum(r['passed'] for r in results),flush=True)


if __name__=='__main__':raise SystemExit(main() or 0)
