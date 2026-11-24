import pytest
from test_engine import Backend,Journal
from simpeople.core.engine import Engine
from simpeople.core.runtime_policy import load_policy

class RecoverBackend(Backend):
    def __init__(self):super().__init__();self.recoveries=[]
    def start(self,h,s):super().start(h,s);return 'route'
    def blocked_reason(self,*_):return {'reason':'traffic_reservation','since_sim_time':0,'blocker_ids':['blocker']}
    def request_recovery(self,h,route):self.recoveries.append((h,route));return {'accepted':True,'original_target_m':[2,0,0]}

@pytest.mark.parametrize('policy,count',[('report',0),('replan_or_report',2)])
def test_recovery_policy_changes_behavior_without_extending_deadline(policy,count):
    backend=RecoverBackend();e=Engine(backend,Journal());e.call('spawn',{'request_id':'spawn','actor_id':'a'})
    tid=e.call('run_activity',{'request_id':'move','actor_id':'a','on_blocked':policy,'steps':[{'action':'move_to','target':[2,0,0],'timeout_s':30}]})['task_id']
    for now in [0,8,16,24,29,31]:e.tick(now)
    task=e.tasks[tid]
    assert len(backend.recoveries)==count and task['status']=='failed'
    assert task['step_deadline_sim_time']==30 and task['error']['code']=='TIMEOUT'
    assert task['steps'][0]['target']==[2.,0.,0.]

def test_runtime_policy_rejects_silent_unsupported_budget(tmp_path):
    import json
    policy=load_policy();policy['max_recovery_attempts']=100
    (tmp_path/'runtime_policy.json').write_text(json.dumps(policy))
    with pytest.raises(ValueError):load_policy(tmp_path)
