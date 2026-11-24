"""A rejected/retried command and native/task IDs retain separate meanings."""
import importlib.util
import json
from pathlib import Path

def test_analyzer_keeps_task_failure_and_does_not_count_sdk_id_as_task(tmp_path):
    path=Path(__file__).resolve().parents[1]/'scripts/analyze_command_outcomes.py'
    spec=importlib.util.spec_from_file_location('command_outcomes',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    events=[]
    for kind in ['tool_call','tool_result','tool_call','tool_result']:
        events.append({'kind':kind,'method':'run_activity','request_id':'r','command_id':'c','attempt_id':'a'})
    events.extend([
        {'kind':'native_task_ended','task_id':7,'native_task_id':7,'logical_task_id':'task','command_id':'c'},
        {'kind':'task_ended','task_id':'task','command_id':'c','task':{'task_id':'task','actor_id':'actor','status':'failed','error':{'code':'TIMEOUT'}}},
        {'kind':'tool_result','method':'spawn','request_id':'orphan'}])
    log=tmp_path/'events.jsonl';log.write_text(''.join(json.dumps(e)+'\n' for e in events));result=module.analyze(log);command=result['commands']['c']
    assert command['task_ids']==['task'] and command['native_task_ids']==['7']
    assert command['task_outcomes']['task']['status']=='failed' and command['errors'][0]['error']['code']=='TIMEOUT'
    assert result['unmatched_request_results']==[{'request_id':'orphan','method':'spawn','calls':0,'results':1}]
