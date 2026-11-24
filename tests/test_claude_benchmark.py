"""Documented stream-shape fixtures, not real Claude language acceptance."""
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from simpeople.core.command_benchmark import call_errors,completed_calls,tool_body
from simpeople.tools import claude_benchmark as host


def request(tid,name,args=None):
    return {'type':'assistant','session_id':'fixture-session','message':{'content':[{'type':'tool_use','id':tid,'name':name,'input':args or {}}]}}


def response(tid,body=None,error=False):
    return {'type':'user','session_id':'fixture-session','message':{'content':[{'type':'tool_result','tool_use_id':tid,'content':[{'type':'text','text':json.dumps(body or {})}],'is_error':error}]}}


def sample():
    return [{'type':'system','subtype':'init','session_id':'fixture-session','model':'fixture-model',
             'tools':['Skill','mcp__plugin_simpeople_simpeople__people_validate_activity'],
             'mcp_servers':[{'name':'plugin_simpeople_simpeople','status':'connected'}],
             'plugins':[{'name':'simpeople','path':'/fixture/frozen/plugin'}]},
            request('skill','Skill',{'skill':'simpeople:simpeople'}),response('skill'),
            request('m1','mcp__plugin_simpeople_simpeople__people_validate_activity',{'actor_id':'a'}),
            response('m1',{'valid':False,'errors':[{'code':'TARGET_INVALID'}]},True),
            {'type':'result','subtype':'success','is_error':False,'session_id':'fixture-session',
             'usage':{'input_tokens':100,'output_tokens':12,'cache_creation_input_tokens':40,'cache_read_input_tokens':30},
             'structured_output':{'status':'rejected','task_ids':[],'reason_codes':['TARGET_INVALID'],'summary':'fixture'},'total_cost_usd':.001}]


def codes(result):return {i['code'] for i in result['issues']}


def test_semantic_error_is_preserved_and_aggregate_usage_includes_cache_once():
    raw=sample();raw[1]['message']['usage']={'input_tokens':99999,'output_tokens':99999}
    raw[4]['tool_use_result']={'structuredContent':{'valid':False,'errors':[{'code':'TARGET_INVALID'}]}}
    result=host.normalize(raw,True)
    assert result['valid'] and result['skill_invoked'] and result['model']=='fixture-model'
    call=completed_calls(result['trace'])[0]
    assert call_errors(call)==['TARGET_INVALID'] and tool_body(call)['valid'] is False
    assert result['usage']=={'input_tokens':170,'output_tokens':12,'cached_input_tokens':30}
    assert sum(r['type']=='turn.completed' for r in result['trace'])==1
    assert result['total_cost_usd']==.001 and result['final']['status']=='rejected'


def test_pending_requests_count_toward_live_budget_but_are_never_completed():
    raw=sample()[:4];live=host.normalize(raw)
    assert live['requested_mcp_calls']==1 and not completed_calls(live['trace'])
    closed=host.normalize(raw,True)
    assert {'UNFINISHED_TOOL_CALLS','FINAL_RESULT_MISSING'}<=codes(closed) and not closed['valid']


@pytest.mark.parametrize('name',['Bash','Read','Agent','mcp__evil_simpeople__people_run_activity'])
def test_foreign_tools_and_delegation_are_not_hidden_from_grading(name):
    raw=sample();raw[3]['message']['content'][0]['name']=name
    result=host.normalize(raw,True)
    assert not result['valid'] and codes(result)&{'FORBIDDEN_HOST_TOOL','FOREIGN_MCP_SERVER'}


@pytest.mark.parametrize('mutation,code',[
    ('duplicate_request','DUPLICATE_OR_MISSING_TOOL_ID'),('duplicate_result','ORPHAN_OR_DUPLICATE_TOOL_RESULT'),
    ('orphan_result','ORPHAN_OR_DUPLICATE_TOOL_RESULT'),('child','CHILD_AGENT_TRACE'),
    ('session','HOST_SESSION_CHANGED'),('replay','REPLAYED_HOST_MESSAGE'),
    ('bad_usage','AGGREGATE_USAGE_MISSING_OR_INVALID'),('no_report','STRUCTURED_REPORT_MISSING'),
    ('cli_error','HOST_RESULT_ERROR'),('skill_error','SIMPEOPLE_SKILL_NOT_INVOKED')])
def test_invalid_or_ambiguous_stream_never_qualifies(mutation,code):
    raw=sample()
    if mutation=='duplicate_request':raw.insert(4,copy.deepcopy(raw[3]))
    elif mutation=='duplicate_result':raw.insert(5,copy.deepcopy(raw[4]))
    elif mutation=='orphan_result':raw[4]['message']['content'][0]['tool_use_id']='unknown'
    elif mutation=='child':raw[3]['parent_tool_use_id']='delegated'
    elif mutation=='session':raw[-1]['session_id']='other-session'
    elif mutation=='replay':raw[4]['isReplay']=True
    elif mutation=='bad_usage':raw[-1]['usage']['input_tokens']=-1
    elif mutation=='no_report':raw[-1]['result']=json.dumps(raw[-1].pop('structured_output'))
    elif mutation=='cli_error':raw[-1]['is_error']=True
    elif mutation=='skill_error':raw[2]['message']['content'][0]['is_error']=True
    result=host.normalize(raw,True)
    assert code in codes(result) and not result['valid']


def test_malformed_blocks_are_reported_instead_of_becoming_success_or_crashing():
    result=host.normalize([None,{'type':'assistant','message':{'content':'not blocks'}},{'type':'user','message':None}],True)
    assert not result['valid'] and 'INVALID_HOST_MESSAGE' in codes(result)


@pytest.mark.parametrize('field,value,code',[
    ('tools',['Skill','Agent'],'UNEXPECTED_AVAILABLE_TOOL'),
    ('mcp_servers',[{'name':'other','status':'connected'}],'MCP_BINDING_NOT_CONNECTED_OR_FOREIGN'),
    ('plugins',[],'SIMPEOPLE_PLUGIN_NOT_LOADED_ONCE'),
    ('tools',None,'INVALID_INIT_TOOLS')])
def test_init_must_prove_the_declared_transport_and_tool_boundary(field,value,code):
    raw=sample();raw[0][field]=value;result=host.normalize(raw,True)
    assert not result['valid'] and code in codes(result)


def test_plugin_path_must_match_the_frozen_session_copy():
    result=host.normalize(sample(),True,expected_plugin_root='/different/plugin')
    assert not result['valid'] and 'SIMPEOPLE_PLUGIN_PATH_MISMATCH' in codes(result)


def fixture_install(tmp_path):
    root=tmp_path/'repo';plugin=tmp_path/'installed';binary=tmp_path/'claude';binary.write_text('fixture binary');binary.chmod(0o700)
    repo=Path(__file__).parents[1]
    for name in host.PLUGIN_FILES:
        for base in (plugin,root/'plugins/claude'):
            target=base/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(repo/'plugins/claude'/name,target)
    return root,plugin,binary


def test_preflight_auth_failure_is_not_a_model_attempt_or_native_write(tmp_path,monkeypatch):
    root,plugin,binary=fixture_install(tmp_path);calls=[]
    def output(args,**kwargs):
        calls.append(args)
        return 'fixture version' if '--version'in args else json.dumps([{'id':'simpeople@ros-claw-simpeople','installPath':str(plugin),'enabled':False}])
    def run(args,**kwargs):calls.append(args);return SimpleNamespace(returncode=1,stdout='{"loggedIn":false,"authMethod":"none","token":"must not persist"}')
    monkeypatch.setattr(host.subprocess,'check_output',output);monkeypatch.setattr(host.subprocess,'run',run)
    result=host.preflight(root,binary)
    assert not result['ready'] and result['attempts_started']==0 and result['checks']['plugin_matches_worktree']
    assert 'token' not in result['auth'] and all('-p' not in c for c in calls)
    assert any('--restricted' in c and c[-2:]==['auth','status'] for c in calls)


def test_launch_scopes_tools_and_freezes_installed_files_without_bypassing_permissions(tmp_path,monkeypatch):
    root,plugin,binary=fixture_install(tmp_path);out=tmp_path/'run';out.mkdir();snap=out/'source_snapshot';snap.mkdir()
    schema=snap/'benchmarks/commands/response.schema.json';schema.parent.mkdir(parents=True);schema.write_text('{"type":"object"}')
    monkeypatch.setattr(host.Path,'home',classmethod(lambda cls:tmp_path/'empty-home'))
    monkeypatch.setenv('ANTHROPIC_MODEL','user-configured-fixture-model')
    proof={'ready':True,'binary':str(binary),'version':'fixture','plugin':{'installPath':str(plugin)},'plugin_hashes':{n:host.sha(plugin/n) for n in host.PLUGIN_FILES}}
    prepared=host.prepare(root,out,snap,'http://127.0.0.1:1',{'controller_id':None},proof);args=prepared['base']
    assert args[args.index('--tools')+1]=='Skill' and args[args.index('--permission-mode')+1]=='dontAsk'
    assert '--dangerously-skip-permissions' not in args and '--strict-mcp-config' in args and '--restricted' in args
    assert args[args.index('--model')+1]=='user-configured-fixture-model'
    binding=json.loads((out/'claude_mcp_binding.json').read_text())['mcpServers'];assert set(binding)=={'plugin_simpeople_simpeople'}
    assert binding['plugin_simpeople_simpeople']['env']['SIMPEOPLE_CONTROLLER_ID']=='simpeople-claude'
    assert all(host.sha(snap/'host_installed/claude'/n)==proof['plugin_hashes'][n] for n in host.PLUGIN_FILES)


def local_preflight(tmp_path,monkeypatch,authenticated=True,validated=True):
    root,plugin,binary=fixture_install(tmp_path);calls=[]
    def output(args,**kwargs):
        calls.append(args)
        assert args==[str(binary),'--version'], 'explicit local mode must not fall back to the global cache'
        return 'fixture version'
    def run(args,**kwargs):
        calls.append(args)
        if args[-2:]==['auth','status']:
            return SimpleNamespace(returncode=0 if authenticated else 1,stdout=json.dumps({'loggedIn':authenticated,'token':'do not retain'}))
        assert args==[str(binary),'plugin','validate',str(plugin)]
        return SimpleNamespace(returncode=0 if validated else 1,stdout='package validator fixture')
    monkeypatch.setattr(host.subprocess,'check_output',output);monkeypatch.setattr(host.subprocess,'run',run)
    return root,plugin,binary,calls


def test_explicit_local_plugin_uses_real_cli_validator_and_matching_frozen_reference(tmp_path,monkeypatch):
    root,plugin,binary,calls=local_preflight(tmp_path,monkeypatch)
    result=host.preflight(root,binary,plugin_dir=plugin)
    assert result['ready'] and result['plugin_loading_mode']=='local-directory'
    assert result['plugin']['scope']=='session' and result['plugin']['installPath']==str(plugin)
    assert result['plugin']['id']=='simpeople' and result['checks']['plugin_matches_worktree']
    assert 'plugin_installed' not in result['checks'] and result['plugin'].get('enabled') is None
    assert 'token' not in result['auth'] and all('-p' not in c for c in calls)


def test_local_package_is_frozen_and_scoped_before_the_first_real_host_attempt(tmp_path,monkeypatch):
    root,plugin,binary,calls=local_preflight(tmp_path,monkeypatch)
    proof=host.preflight(root,binary,plugin_dir=plugin);out=tmp_path/'run';out.mkdir();snap=out/'source_snapshot';snap.mkdir()
    schema=snap/'benchmarks/commands/response.schema.json';schema.parent.mkdir(parents=True);schema.write_text('{"type":"object"}')
    monkeypatch.setattr(host.Path,'home',classmethod(lambda cls:tmp_path/'empty-home'))
    prepared=host.prepare(root,out,snap,'http://127.0.0.1:1',{'controller_id':None},proof)
    args=prepared['base'];cached=snap/'host_installed/claude'
    assert args[args.index('--plugin-dir')+1]==str(cached)
    assert prepared['manifest']['plugin_loading_mode']=='local-directory'
    assert 'explicit local' in prepared['manifest']['installed_plugin_binding_mode']
    assert '--strict-mcp-config' in args and '--dangerously-skip-permissions' not in args
    assert all(host.sha(cached/n)==proof['plugin_hashes'][n] for n in host.PLUGIN_FILES)


@pytest.mark.parametrize('fault',['unauthenticated','invalid_package','missing_directory','missing_skill','changed_skill','wrong_reference','bad_launcher','foreign_mcp'])
def test_local_directory_cannot_hide_auth_package_or_reference_failure(tmp_path,monkeypatch,fault):
    root,plugin,binary,calls=local_preflight(tmp_path,monkeypatch,authenticated=fault!='unauthenticated',validated=fault!='invalid_package')
    reference=root/'plugins/claude'
    if fault=='missing_skill':(plugin/'skills/simpeople/SKILL.md').unlink()
    elif fault=='changed_skill':(plugin/'skills/simpeople/SKILL.md').write_text('stale cache')
    elif fault=='wrong_reference':(reference/'skills/simpeople/SKILL.md').write_text('different frozen source')
    elif fault in {'bad_launcher','foreign_mcp'}:
        p=plugin/'.mcp.json';data=json.loads(p.read_text())
        if fault=='bad_launcher':data['mcpServers']['simpeople']['command']='foreign-command'
        else:data['mcpServers']['other']={'command':'foreign-command'}
        # Match the reference so the launcher check must independently reject it.
        p.write_text(json.dumps(data));(reference/'.mcp.json').write_bytes(p.read_bytes())
    result=host.preflight(root,binary,reference_root=reference,plugin_dir=tmp_path/'missing' if fault=='missing_directory' else plugin)
    assert not result['ready'] and result['attempts_started']==0
    assert all('-p' not in c for c in calls)


@pytest.mark.parametrize('race',['after_preflight','while_copying'])
def test_plugin_update_race_cannot_change_the_executed_skill_silently(tmp_path,monkeypatch,race):
    root,plugin,binary,calls=local_preflight(tmp_path,monkeypatch)
    proof=host.preflight(root,binary,plugin_dir=plugin);out=tmp_path/'run';out.mkdir();snap=out/'source_snapshot';snap.mkdir()
    skill=plugin/'skills/simpeople/SKILL.md'
    if race=='after_preflight':skill.write_text('new unreviewed skill')
    else:
        original=host.shutil.copy2
        def replaced(source,target):
            if Path(source)==skill:skill.write_text('new unreviewed skill during copy')
            return original(source,target)
        monkeypatch.setattr(host.shutil,'copy2',replaced)
    with pytest.raises(ValueError,match='Claude plugin changed'):
        host.prepare(root,out,snap,'http://127.0.0.1:1',{'controller_id':None},proof)
