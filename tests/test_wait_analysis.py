import importlib.util
import json
from pathlib import Path

def module():
    path=Path(__file__).resolve().parents[1]/'scripts/analyze_waits.py';spec=importlib.util.spec_from_file_location('wait_analysis',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_cutoff_keeps_unfinished_ticket_instead_of_counting_shutdown_release(tmp_path):
    row={'ticket_id':'t','actor_id':'a','resource_id':'q','status':'waiting','capacity':1,'outside_capacity':1,'requested_sim_time':2,'admitted_sim_time':None}
    events=[{'kind':'admission_queued','cursor':1,'sim_time':2,'ticket':row},
            {'kind':'admission_ended','cursor':2,'sim_time':10,'ticket':{**row,'status':'cancelled'}}]
    (tmp_path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events));(tmp_path/'benchmark_done.json').write_text(json.dumps({'event_cursor':1,'time_s':10}))
    result=module().analyze(tmp_path)
    assert result['active_tickets_at_cutoff']==1 and result['tickets'][0]['unfinished_wait_lower_bound_sim_s']==8

def test_unserved_wait_stays_in_report_and_does_not_improve_served_percentile(tmp_path):
    events=[{'kind':'traffic_wait_started','route_id':'one','sim_time':1}, {'kind':'traffic_wait_ended','route_id':'one','sim_time':3},
            {'kind':'traffic_wait_started','route_id':'two','sim_time':2}]
    (tmp_path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events));(tmp_path/'benchmark_done.json').write_text(json.dumps({'time_s':20}))
    result=module().analyze(tmp_path)
    assert result['served_traffic_wait']['p95_sim_s']==2 and result['unserved_traffic_waits']==1
    assert result['traffic_waits'][1]['wait_lower_bound_sim_s']==18

def test_cancelled_queue_wait_ends_at_cancellation_not_measurement_cutoff(tmp_path):
    events=[{'kind':'step_started','task_id':'t','actor_id':'a','index':0,'sim_time':1,'step':{'action':'queue','target':'q'}},
        {'kind':'task_ended','task_id':'t','sim_time':3,'task':{'status':'cancelled'}}]
    (tmp_path/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    (tmp_path/'benchmark_done.json').write_text(json.dumps({'time_s':120}))
    result=module().analyze(tmp_path);row=result['queue_steps'][0]
    assert row['wait_until_terminal_sim_s']==2 and 'unfinished_wait_lower_bound_sim_s' not in row
    assert result['unfinished_queue_steps']==0 and result['terminal_without_queue_completion']=={'cancelled':1}
