import copy
from pathlib import Path
import pytest
from simpeople.core.command_benchmark import load_suite,grade,tool_body,error_codes,call_errors,summarize,fixture_errors

ROOT=Path(__file__).resolve().parents[1]


def suite():return load_suite(ROOT/'benchmarks/commands/commandbench_v1.json',ROOT/'schemas/command-case.schema.json')


def call(name,args=None,body=None):
    return {'type':'item.completed','item':{'type':'mcp_tool_call','server':'plugin_simpeople_simpeople','tool':name,'arguments':args or {},'result':{'content':[{'type':'text','text':__import__('json').dumps(body or {})}]},'status':'completed'}}


def evidence():
    actors=[{'actor_id':aid,'actor_instance_id':aid+'_instance','control_epoch':1,'task':{'task_id':aid+'_old','status':'running'},'observation':{'ready':True,'position_m':[-15,-6,0],'speed_mps':0},'seat':None,'seat_cleanup_pending':False} for aid in ['a','b','c','witness']]
    before={'actors':actors,'episode_id':'e','sim_time':0};after=copy.deepcopy(before);after['sim_time']=5
    task={'task_id':'new','actor_id':'a','status':'succeeded','steps':[{'action':'move_to','target':[-15,-2,0]}],'started_sim_time':1,'finished_sim_time':4}
    after['actors'][0].update(control_epoch=2,task=task,observation={'ready':True,'position_m':[-15,-2,0],'speed_mps':0})
    events=[{'kind':'tool_call','method':'validate_activity','params':{'actor_id':'a'}},{'kind':'tool_result','method':'validate_activity','result':{'valid':True,'steps':task['steps']}},{'kind':'task_accepted','task':{**task,'status':'accepted'}},{'kind':'task_ended','task':task}]
    trajectory=[{'actor_id':'witness','ready':True,'position_m':[18,y,0]} for y in [16,17]]
    trace=[call('people_session',{'action':'info'},{'session_id':'s','episode_id':'e'}),call('people_session',{'action':'preflight'},{'ready':True}),call('people_validate_activity',body={'valid':True}),call('people_list_actions',body={'actor_id':'a','actions':{'walk':{'status':'verified'}}})]+[{'type':'turn.completed','usage':{'input_tokens':2000,'output_tokens':100}}]
    final={'status':'completed','task_ids':['new'],'reason_codes':[]};execution={'returncode':0,'interrupted':None,'wall_s':10}
    return [suite()['cases'][0],before,after,events,trajectory,trace,final,execution]


def test_dataset_keeps_twenty_cases_and_unrun_holdout_split():
    cases=suite()['cases'];assert len(cases)==20
    assert sum(c['split']=='development' for c in cases)==15
    assert sum(c['split']=='holdout' for c in cases)==5
    assert any(c.get('created_actors') for c in cases)


def test_success_requires_native_completion_world_goal_and_preserved_witness():
    args=evidence();assert grade(*args)['passed']
    args[2]['actors'][0]['task']['status']='running';args[3]=args[3][:-1]
    assert not grade(*args)['passed']  # Host says completed, native did not.


@pytest.mark.parametrize('fault',['wrong_goal','other_actor_changed','witness_still','episode_changed','invented_id','shell','no_preflight','token_budget'])
def test_host_self_report_cannot_mask_constraint_failure(fault):
    a=evidence()
    if fault=='wrong_goal':a[2]['actors'][0]['observation']['position_m']=[10,10,0]
    if fault=='other_actor_changed':a[2]['actors'][1]['control_epoch']+=1
    if fault=='witness_still':a[4]=a[4][:1]
    if fault=='episode_changed':a[2]['episode_id']='new'
    if fault=='invented_id':a[6]['task_ids']=['made_up']
    if fault=='shell':a[5].append({'type':'item.completed','item':{'type':'command_execution'}})
    if fault=='no_preflight':a[5]=[e for e in a[5] if e.get('item',{}).get('arguments',{}).get('action')!='preflight']
    if fault=='token_budget':a[5][-1]['usage']['output_tokens']=12001
    assert not grade(*a)['passed']


def test_negative_refusal_is_separate_and_requires_preserved_tasks():
    a=evidence();a[0]=suite()['cases'][11];a[2]=copy.deepcopy(a[1]);a[2]['sim_time']=5;a[3]=[];a[6]={'status':'rejected','task_ids':[],'reason_codes':['ACTION_UNSUPPORTED']}
    result=grade(*a);assert result['passed'] and result['polarity']=='negative'
    a[2]['actors'][0]['task']={'task_id':'silently_replaced'}
    assert not grade(*a)['passed']


def test_cancel_acceptance_does_not_prove_stopping_or_recovery_order():
    a=evidence();a[0]=suite()['cases'][7];a[3][-1]['task'].update(status='cancelled',physical_stop_verified=False)
    a[2]['actors'][0]['task']=a[3][-1]['task']
    result=grade(*a);assert not result['checks']['predicate_0_cancelled_then_wait']


def test_batch_item_errors_survive_successful_mcp_transport():
    c=call('people_crowd',body={'accepted':1,'rejected':1,'results':[{'error':{'code':'TARGET_INVALID'}}]})['item']
    assert error_codes(tool_body(c))==['TARGET_INVALID']


def test_cli_failed_semantic_result_is_not_labeled_broken_transport():
    c=call('people_validate_activity',body={'error':{'code':'TARGET_INVALID'}})['item']
    c.update(status='failed',error=None)
    assert call_errors(c)==['TARGET_INVALID']
    c['result']=None;c['error']={'message':'connection closed'}
    assert call_errors(c)==['MCP_TRANSPORT_ERROR']


def test_intended_partial_batch_refusal_is_not_an_extra_repair_on_real_cli_shape():
    a=evidence();a[0]=suite()['cases'][14]
    bad=call('people_validate_activity',{'actor_id':'b','steps':[{'action':'move_to','target':'missing'}]},{'error':{'code':'TARGET_INVALID'}})
    bad['item'].update(status='failed',error=None)
    a[5].insert(0,bad)
    r=grade(*a)
    assert r['rejected_plan_variants']==0 and r['first_parameters_passed']


def test_negative_diagnostic_cannot_report_invented_task_ids():
    a=evidence();a[0]=suite()['cases'][11];a[2]=copy.deepcopy(a[1]);a[2]['sim_time']=5;a[3]=[]
    a[6]={'status':'rejected','task_ids':['invented'],'reason_codes':['ACTION_UNSUPPORTED']}
    r=grade(*a)
    assert not r['checks']['reported_task_ids_known'] and not r['passed']


def test_transport_failure_cannot_be_graded_as_successful_read_or_refusal():
    a=evidence();a[0]=suite()['cases'][11];a[2]=copy.deepcopy(a[1]);a[2]['sim_time']=5;a[3]=[];a[6]={'status':'rejected','task_ids':[],'reason_codes':['ACTION_UNSUPPORTED']}
    a[5]=[call('people_session',{'action':'info'},{'error':{'code':'BACKEND_UNAVAILABLE'}}),call('people_session',{'action':'preflight'},{'error':{'code':'BACKEND_UNAVAILABLE'}}),call('people_list_actions',body={'error':{'code':'BACKEND_UNAVAILABLE'}}),a[5][-1]]
    result=grade(*a);assert not result['passed'] and not result['checks']['session_and_preflight_read'] and not result['checks']['predicate_0_negative']


def test_matching_group_today_does_not_prove_selector_was_frozen():
    a=evidence();a[0]=suite()['cases'][5]
    a[5].append(call('people_crowd',{'operation':'run_activity','selector':{'group':'crew'}},{'results':[{'actor_id':'a'},{'actor_id':'b'}]}))
    assert not grade(*a)['checks']['predicate_4_batch']
    a[5][-1]['item']['arguments']['selector']['actor_ids']=['a','b']
    assert grade(*a)['checks']['predicate_4_batch']


def test_clear_actor_metadata_does_not_hide_a_leaked_seat_lease():
    a=evidence();a[0]=suite()['cases'][3];a[2]['resource_snapshot']={'resources':{'owners':{'seat_00':'a'},'admission':{}},'queues':{}}
    assert not grade(*a)['checks']['predicate_2_seat_clear']
    a[2]['resource_snapshot']['resources']['owners']={}
    assert grade(*a)['checks']['predicate_2_seat_clear']


def test_partial_pilot_and_correct_refusals_cannot_inflate_positive_rate():
    good=grade(*evidence());good['repetition']=1
    bad=copy.deepcopy(good);bad.update(case_id='c02',passed=False)
    rejected=copy.deepcopy(good);rejected.update(case_id='c12',polarity='negative')
    manifest={'host':'test','model':'test','case_ids':['c01','c02','c12'],'repetitions':3,'formal':False}
    r=summarize(manifest,[good,bad,rejected])
    assert not r['passed'] and r['unrun_attempts']==6
    assert r['positive_after_bounded_repairs']['rate']==.5
    assert r['negative_correct_rejections']['rate']==1


def test_rejected_proposals_also_consume_the_repair_budget():
    a=evidence()
    for i in range(3):a[5].append(call('people_validate_activity',{'actor_id':'a','steps':[{'action':'move_to','target':'bad_'+str(i)}]}, {'error':{'code':'TARGET_INVALID'}}))
    result=grade(*a)
    assert result['repairs']==3 and not result['checks']['bounded_repairs']


def test_repeated_delivery_of_the_same_invalid_proposal_is_one_variant():
    a=evidence()
    for i in range(3):a[5].append(call('people_validate_activity',{'actor_id':'a','steps':[{'action':'move_to','target':'bad'}]}, {'error':{'code':'TARGET_INVALID'}}))
    result=grade(*a)
    assert result['rejected_plan_variants']==1 and result['checks']['bounded_repairs']


def test_reporting_an_unaffected_old_task_does_not_identify_completed_work():
    a=evidence();a[6]['task_ids']=['b_old']
    assert not grade(*a)['checks']['reported_actual_task_ids']


def test_ready_old_pose_is_not_a_valid_fresh_fixture():
    case=suite()['cases'][0]
    actors=[{'actor_id':a['actor_id'],'observation':{'ready':True,'position_m':a['position_m']}} for a in [*case['fixture']['actors'],{'actor_id':'witness','position_m':[18,16,0]}]]
    assert fixture_errors(case,{'actors':actors})==[]
    actors[0]['observation']['position_m']=[10,-11,0]
    error=fixture_errors(case,{'actors':actors})
    assert error[0]['kind']=='spawn_position_mismatch' and error[0]['error_m']>20
