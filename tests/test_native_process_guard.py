"""A CPU host probe is not a GPU job; unknown reserved jobs stay blockers."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('native_process_guard',Path(__file__).parents[1]/'scripts/native_process_guard.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)


@pytest.fixture
def preflight(tmp_path):
    script=tmp_path/'scripts/run_command_benchmark.py';script.parent.mkdir();script.write_text('# reviewed Native-free preflight branch\n')
    digest=hashlib.sha256(script.read_bytes()).hexdigest()
    args=['python3',str(script),'--host','claude','--host-preflight-only','--run-id','iter1115host-preflight']
    return script,digest,args


@pytest.mark.parametrize('relative',[False,True])
def test_only_the_exact_verified_cpu_preflight_is_exempt(preflight,relative):
    script,digest,args=preflight;cwd=script.parent.parent
    if relative:args[1]='scripts/run_command_benchmark.py'
    assert guard.owned_job_id(args,cwd,cpu_preflight_script=script,cpu_preflight_sha256=digest) is None


@pytest.mark.parametrize('fault',['changed_source','different_path','same_name_elsewhere','no_flag','flag_value','shell','no_hash','unknown_executable','python_lookalike'])
def test_unverified_or_real_runtime_jobs_cannot_be_excused_as_cpu(preflight,fault,tmp_path):
    script,digest,args=preflight;approved=script
    if fault=='changed_source':script.write_text('# changed after approval\n')
    elif fault=='different_path':args[1]='scripts/kit_main.py'
    elif fault=='same_name_elsewhere':
        other=tmp_path/'other/run_command_benchmark.py';other.parent.mkdir();other.write_bytes(script.read_bytes());args[1]=str(other)
    elif fault=='no_flag':args.remove('--host-preflight-only')
    elif fault=='flag_value':args[args.index('--host-preflight-only')]='--host-preflight-only=false'
    elif fault=='shell':args[0]='/bin/bash'
    elif fault=='no_hash':digest=None
    elif fault=='python_lookalike':args[0]='/some/python-unknown-runtime'
    else:args[0]='/some/isaac-runtime'
    assert guard.owned_job_id(args,tmp_path,cpu_preflight_script=approved,cpu_preflight_sha256=digest)=='iter1115host-preflight'


def test_unknown_reserved_model_job_remains_a_blocker(tmp_path):
    assert guard.owned_job_id(['python3','worker.py','--run-id','iter1114-model'],tmp_path)=='iter1114-model'
    assert guard.owned_job_id(['python3','worker.py','--run-id','unrelated-user-job'],tmp_path) is None
    assert guard.owned_job_id(['python3','worker.py','--run-id'],tmp_path) is None


@pytest.mark.parametrize('run_id', ['iter1116hk-cancel-03', 'iter1117-model', 'iter1201-native', 'iter0101-probe'])
@pytest.mark.parametrize('form', ['separate', 'equals'])
def test_reserved_jobs_remain_visible_after_the_original_test_dates(tmp_path, run_id, form):
    flags = ['--run-id', run_id] if form == 'separate' else ['--run-id='+run_id]
    assert guard.owned_job_id(['python3', 'worker.py', *flags], tmp_path) == run_id


@pytest.mark.parametrize('run_id', ['unrelated-user-job', 'iterator', 'iter12', 'iterabcd'])
def test_nonreserved_jobs_are_not_claimed(tmp_path, run_id):
    assert guard.owned_job_id(['python3', 'worker.py', '--run-id='+run_id], tmp_path) is None


def test_ambiguous_run_ids_never_receive_the_cpu_exception(preflight, tmp_path):
    script, digest, args = preflight
    args.extend(['--run-id=iter1116-native'])
    assert guard.owned_job_id(args, tmp_path, cpu_preflight_script=script,
                              cpu_preflight_sha256=digest) == 'iter1115host-preflight'


def test_an_unrelated_first_id_does_not_hide_a_reserved_job(tmp_path):
    args = ['python3', 'worker.py', '--run-id', 'user-job', '--run-id=iter1116-native']
    assert guard.owned_job_id(args, tmp_path) == 'iter1116-native'
