"""Claude CLI boundary for CommandBench; never fabricates model/native results.

The normalized trace is a grading view, not a Codex execution. Always retain
the original stream alongside it. Parser fixtures cannot qualify a real host.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess

PLUGIN_FILES=('.claude-plugin/plugin.json','.mcp.json','skills/simpeople/SKILL.md')
SERVERS={'plugin_simpeople_simpeople'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def preflight(root,binary=None,reference_root=None,plugin_dir=None):
    root=Path(root)
    binary=Path(binary or root/'.runtime/claude-linux/node_modules/@anthropic-ai/claude-code-linux-x64/claude').resolve()
    result={'host':'Claude Code','binary':str(binary),'ready':False,'checks':{},'attempts_started':0,
            'plugin_loading_mode':'local-directory' if plugin_dir is not None else 'installed-marketplace'}
    if not binary.is_file() or not os.access(binary,os.X_OK):
        result['checks']['executable']=False;return result
    result['checks']['executable']=True
    result['version']=subprocess.check_output([str(binary),'--version'],text=True,timeout=30).strip()
    result['binary_sha256']=sha(binary)
    auth=subprocess.run([str(binary),'--restricted','--setting-sources','','auth','status'],capture_output=True,text=True,timeout=30)
    try:state=json.loads(auth.stdout)
    except ValueError:state={}
    # Whitelist diagnostic fields; do not retain credentials/settings dumps.
    result['auth']={k:state[k] for k in ('loggedIn','authMethod','apiProvider','configDirectory') if k in state}
    result['checks']['authenticated']=auth.returncode==0 and state.get('loggedIn') is True
    if plugin_dir is not None:
        plugin=Path(plugin_dir).resolve()
        result['checks']['explicit_plugin_directory']=plugin.is_dir()
        if not plugin.is_dir():return result
        validation=subprocess.run([str(binary),'plugin','validate',str(plugin)],capture_output=True,text=True,timeout=30)
        result['checks']['local_plugin_validated']=validation.returncode==0
        result['plugin_validation_exit_code']=validation.returncode
        installed={'installPath':str(plugin),'scope':'session'}
    else:
        plugins=json.loads(subprocess.check_output([str(binary),'plugin','list','--json'],text=True,timeout=30))
        installed=next((p for p in plugins if p.get('id')=='simpeople@ros-claw-simpeople'),None)
        result['checks']['plugin_installed']=installed is not None
    if installed:
        plugin=Path(installed['installPath']);result['plugin']={k:installed.get(k) for k in ('id','version','scope','enabled','installPath')}
        result['checks']['plugin_files_present']=all((plugin/n).is_file() for n in PLUGIN_FILES)
        if result['checks']['plugin_files_present']:
            result['plugin_hashes']={n:sha(plugin/n) for n in PLUGIN_FILES}
            reference=Path(reference_root) if reference_root is not None else root/'plugins/claude'
            result['checks']['plugin_matches_worktree']=all(sha(reference/n)==h for n,h in result['plugin_hashes'].items())
            try:
                servers=json.loads((plugin/'.mcp.json').read_text())['mcpServers'];entry=servers['simpeople']
                result['checks']['installed_launcher']=set(servers)=={'simpeople'} and entry.get('command')=='simpeople' and entry.get('args')==['mcp']
                if plugin_dir is not None:
                    metadata=json.loads((plugin/'.claude-plugin/plugin.json').read_text())
                    result['plugin'].update(id=metadata.get('name'),version=metadata.get('version'))
            except (ValueError,KeyError,TypeError,AttributeError):
                result['checks']['installed_launcher']=False
    result['ready']=all(result['checks'].values())
    return result


def prepare(root,out,snap,endpoint,session,proof):
    """Freeze a per-session copy of the installed plugin and scoped launcher."""
    if not proof['ready']:raise ValueError('Claude host preflight is not ready')
    root,out,snap=map(Path,(root,out,snap));plugin=Path(proof['plugin']['installPath'])
    cached=snap/'host_installed/claude';cached.mkdir(parents=True)
    for name in PLUGIN_FILES:
        if sha(plugin/name)!=proof['plugin_hashes'][name]:raise ValueError('Claude plugin changed after preflight: '+name)
        target=cached/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(plugin/name,target)
        if sha(target)!=proof['plugin_hashes'][name]:raise ValueError('Claude plugin changed while freezing: '+name)
    launcher=json.loads((cached/'.mcp.json').read_text())['mcpServers']['simpeople'];client=launcher.get('env',{}).get('SIMPEOPLE_CONTROLLER_ID','simpeople-claude')
    if session['controller_id'] not in (None,client):raise ValueError('dedicated runtime is owned by another controller')
    env=os.environ.copy();env.update(SIMPEOPLE_ENDPOINT=endpoint,SIMPEOPLE_CONTROLLER_ID=client,PYTHONPATH=str(snap/'src'),PATH=str(root/'.venv-controller/bin')+os.pathsep+env['PATH']);env.pop('SIMPEOPLE_MOTION_ENDPOINT',None)
    import tempfile
    workspace=Path(tempfile.mkdtemp(prefix='simpeople-claude-commandbench-'))
    (workspace/'CLAUDE.md').write_text('SimPeople product acceptance only. Use the local SimPeople plugin and its Skill. No coding, file access, shell, web, other plugins, delegation or scene reset. Native state decides completion.\n')
    binding={**launcher,'env':{**launcher.get('env',{}),**{k:env[k] for k in ('SIMPEOPLE_ENDPOINT','SIMPEOPLE_CONTROLLER_ID','PYTHONPATH','PATH')}}}
    mcp=out/'claude_mcp_binding.json';mcp.write_text(json.dumps({'mcpServers':{'plugin_simpeople_simpeople':binding}},indent=2)+'\n')
    # Preserve the user's configured model; do not select a replacement.
    model=env.get('ANTHROPIC_MODEL')
    settings=Path.home()/'.claude/settings.json'
    if not model and settings.is_file():model=json.loads(settings.read_text()).get('model')
    args=[proof['binary'],'-p','--verbose','--output-format','stream-json','--no-session-persistence','--restricted','--setting-sources','','--tools','Skill','--permission-mode','dontAsk','--allowedTools','mcp__plugin_simpeople_simpeople__*,Skill(simpeople:simpeople)','--plugin-dir',str(cached),'--strict-mcp-config','--mcp-config',str(mcp),'--json-schema',(snap/'benchmarks/commands/response.schema.json').read_text()]
    if model:args+=['--model',model]
    manifest={'host':'Claude Code','host_version':proof['version'],'model':model or 'CLI default; actual init model must be recorded','plugin':proof['plugin'],'installed_plugin_hashes':proof['plugin_hashes'],'installed_cache_root':str(plugin),'installed_cache_hashes':proof['plugin_hashes'],
              'installed_plugin_binding_mode':'Session-only load of frozen '+('explicit local' if proof.get('plugin_loading_mode')=='local-directory' else 'installed')+' plugin directory, explicit qualified MCP transport and Skill invocation; not automatic marketplace discovery.',
              'plugin_loading_mode':proof.get('plugin_loading_mode','installed-marketplace'),
              'filesystem_sandbox':'Built-in tool set limited to Skill; restricted mode and dontAsk; only the qualified local SimPeople MCP is approved.',
              'model_policy':'Preserve existing ANTHROPIC_MODEL/user model; otherwise record actual CLI init model and reject changes within the matrix.',
              'token_budget_enforcement':'Input includes uncached plus cache creation and read tokens; only final aggregate usage is counted, not assistant deltas.',
              'cost_note':'Only actual CLI total_cost_usd is recorded when present; no price estimate.','workspace':str(workspace)}
    return {'client':client,'env':env,'workspace':workspace,'base':args,'manifest':manifest,'cache':plugin,'cached_files':[plugin/n for n in PLUGIN_FILES]}


def normalize(rows,finalize=False,expected_plugin_root=None):
    """Correlate completed tool_use/result pairs without hiding unsafe events."""
    trace=[];issues=[];pending={};done=set();inits=[];results=[];requests=0;good_skills=set()
    def issue(code,**details):issues.append({'code':code,**details})
    for row in rows:
        if not isinstance(row,dict):issue('INVALID_HOST_MESSAGE');continue
        if row.get('agent_id') or row.get('parent_tool_use_id'):
            issue('CHILD_AGENT_TRACE');continue
        if row.get('isReplay'):issue('REPLAYED_HOST_MESSAGE');continue
        kind=row.get('type')
        if kind=='system' and row.get('subtype')=='init':
            inits.append(row)
            tools=row.get('tools',[])
            if not isinstance(tools,list) or not all(isinstance(n,str) for n in tools):issue('INVALID_INIT_TOOLS');tools=[]
            for name in tools:
                if name not in ('Skill','StructuredOutput','ToolSearch') and not any(name.startswith('mcp__'+server+'__') for server in SERVERS):issue('UNEXPECTED_AVAILABLE_TOOL',name=name)
            servers=row.get('mcp_servers',[])
            if not isinstance(servers,list) or not servers or any(not isinstance(s,dict) or s.get('name') not in SERVERS or s.get('status')!='connected' for s in servers):issue('MCP_BINDING_NOT_CONNECTED_OR_FOREIGN')
            plugins=row.get('plugins',[])
            if not isinstance(plugins,list):issue('INVALID_INIT_PLUGINS');plugins=[]
            plugins=[p for p in plugins if isinstance(p,dict) and p.get('name')=='simpeople']
            if len(plugins)!=1:issue('SIMPEOPLE_PLUGIN_NOT_LOADED_ONCE')
            elif expected_plugin_root is not None and Path(plugins[0].get('path','')).resolve()!=Path(expected_plugin_root).resolve():issue('SIMPEOPLE_PLUGIN_PATH_MISMATCH')
        elif kind=='assistant':
            message=row.get('message',{});blocks=message.get('content',[]) if isinstance(message,dict) else None
            if not isinstance(blocks,list):issue('INVALID_ASSISTANT_CONTENT');continue
            for block in blocks:
                if not isinstance(block,dict):issue('INVALID_ASSISTANT_BLOCK');continue
                if block.get('type')!='tool_use':continue
                tid=block.get('id');name=block.get('name','');args=block.get('input',{})
                if not isinstance(tid,str) or not tid or tid in pending or tid in done:issue('DUPLICATE_OR_MISSING_TOOL_ID',tool_use_id=tid);continue
                if not isinstance(name,str):issue('INVALID_TOOL_NAME',tool_use_id=tid);continue
                if not isinstance(args,dict):issue('INVALID_TOOL_ARGUMENTS',tool_use_id=tid);args={}
                if name.startswith('mcp__'):
                    requests+=1
                    pieces=name[5:].rsplit('__',1)
                    if len(pieces)!=2:issue('INVALID_MCP_TOOL_NAME',name=name);continue
                    server,tool=pieces
                    if server not in SERVERS:issue('FOREIGN_MCP_SERVER',server=server)
                    pending[tid]={'id':tid,'type':'mcp_tool_call','server':server,'tool':tool,'arguments':args}
                elif name=='Skill' and args.get('skill')=='simpeople:simpeople':
                    pending[tid]={'id':tid,'type':'skill_invocation','arguments':args}
                elif name in ('StructuredOutput','ToolSearch'):
                    pending[tid]={'id':tid,'type':'host_report' if name=='StructuredOutput' else 'tool_discovery','arguments':args}
                else:
                    issue('FORBIDDEN_HOST_TOOL',name=name);pending[tid]={'id':tid,'type':'forbidden_host_tool','tool':name,'arguments':args}
        elif kind=='user':
            message=row.get('message',{});content=message.get('content',[]) if isinstance(message,dict) else None
            if not isinstance(content,list):issue('INVALID_USER_CONTENT');continue
            blocks=[b for b in content if isinstance(b,dict) and b.get('type')=='tool_result']
            for block in blocks:
                tid=block.get('tool_use_id')
                if not isinstance(tid,str):issue('INVALID_TOOL_RESULT_ID');continue
                item=pending.pop(tid,None)
                if item is None:issue('ORPHAN_OR_DUPLICATE_TOOL_RESULT',tool_use_id=tid);continue
                done.add(tid);failed=block.get('is_error') is True;content=block.get('content',[])
                if isinstance(content,str):content=[{'type':'text','text':content}]
                if not isinstance(content,list):issue('INVALID_TOOL_RESULT',tool_use_id=tid);content=[]
                result={'content':content,'isError':failed}
                structured=row.get('tool_use_result')
                if len(blocks)==1 and isinstance(structured,dict) and structured.get('isError') is True:failed=True;result['isError']=True
                if len(blocks)==1 and isinstance(structured,dict) and isinstance(structured.get('structuredContent'),dict):result['structuredContent']=structured['structuredContent']
                if item['type']=='skill_invocation' and not failed:good_skills.add(tid)
                item.update(status='failed' if failed else 'completed',result=result)
                trace.append({'type':'item.completed','item':item})
        elif kind=='result':results.append(row)
    final={};usage={};cost=None;model=inits[0].get('model') if len(inits)==1 else None
    if results:
        if len(results)!=1:issue('MULTIPLE_FINAL_RESULTS')
        result=results[-1]
        if result.get('is_error') or result.get('subtype')!='success':issue('HOST_RESULT_ERROR',subtype=result.get('subtype'))
        elif isinstance(result.get('structured_output'),dict):final=result['structured_output']
        elif finalize:issue('STRUCTURED_REPORT_MISSING')
        raw=result.get('usage',{})
        keys=('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')
        if isinstance(raw,dict) and all(isinstance(raw.get(k,0),int) and not isinstance(raw.get(k,0),bool) and raw.get(k,0)>=0 for k in keys) and 'input_tokens' in raw and 'output_tokens' in raw:
            usage={'input_tokens':sum(raw.get(k,0) for k in ('input_tokens','cache_creation_input_tokens','cache_read_input_tokens')),'output_tokens':raw['output_tokens'],'cached_input_tokens':raw.get('cache_read_input_tokens',0)}
            trace.append({'type':'turn.completed','usage':usage})
        elif finalize:issue('AGGREGATE_USAGE_MISSING_OR_INVALID')
        value=result.get('total_cost_usd')
        if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0:cost=value
        if result.get('permission_denials'):issue('HOST_PERMISSION_DENIALS')
    if finalize:
        if len(inits)!=1:issue('HOST_INIT_MISSING_OR_MULTIPLE')
        elif inits[0].get('plugin_errors'):issue('PLUGIN_LOAD_ERRORS')
        if not isinstance(model,str) or not model:issue('ACTUAL_MODEL_NOT_RECORDED')
        if not results:issue('FINAL_RESULT_MISSING')
        if pending:issue('UNFINISHED_TOOL_CALLS',tool_use_ids=sorted(pending))
        if not good_skills:issue('SIMPEOPLE_SKILL_NOT_INVOKED')
        if inits:
            expected=inits[0].get('session_id')
            if any(r.get('session_id') not in (None,expected) for r in rows):issue('HOST_SESSION_CHANGED')
    return {'trace':trace,'final':final,'issues':issues,'valid':not issues,'requested_mcp_calls':requests,'pending_tool_ids':sorted(pending),'model':model,'usage':usage,'total_cost_usd':cost,'skill_invoked':bool(good_skills)}
