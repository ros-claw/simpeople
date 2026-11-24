"""Qualification depends on changed helper bytes and effective runtime mode."""
import ast,copy,hashlib,importlib.util,json,shutil
from pathlib import Path
from types import SimpleNamespace
import pytest
R=Path(__file__).resolve().parents[1];S=R
def fingerprint_module():
 spec=importlib.util.spec_from_file_location('candidate_fingerprint',S/'src/simpeople/core/gesture_profiles.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
@pytest.fixture
def fixture(tmp_path):
 package=tmp_path/'src/simpeople';fp=fingerprint_module()
 for n in fp.IMPLEMENTATION_FILES:
  p=package/n;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(S/'src/simpeople'/n,p)
 config=tmp_path/'config';config.mkdir();digest=fp.implementation_revision(package);flags={'cooperative_finite_stop':True};entry=dict(status='discovered',cooperative_finite_cycle=True,source_sha256={'runtime_implementation':digest,'clip':'clipsha'},execution_runtime_flags=flags,runtime_revision='sdk');proof={'source_sha256':copy.deepcopy(entry['source_sha256']),'execution_runtime_flags':dict(flags),'runtime_revision':'sdk','asset_sha256':'assetsha','evidence':'synthetic_unit_test_only'};b=SimpleNamespace(custom_actions={'finite':entry},instances={'actor':{'asset_id':'asset'}},assets=[{'asset_id':'asset','content_hash':'assetsha'}],config_dir=config,runtime_revision='sdk',cooperative_finite_stop_probe_enabled=True)
 def save():(config/'custom_action_acceptance.json').write_text(json.dumps({'finite':{'asset':proof}}))
 save();return b,entry,proof,save,package,fp

def describe(fixture,old=False):
 b,entry,proof,save,package,fp=fixture;file=S/'src/simpeople/backends/native/custom_actions.py';tree=ast.parse(file.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='describe');scope={'__file__':str(package/'backends/native/custom_actions.py'),'Path':Path,'json':json,'implementation_revision':fp.implementation_revision};exec(compile(ast.Module(body=[node],type_ignores=[]),str(file),'exec'),scope);return scope['describe'](b,'actor')['clips']['finite']

def test_exact_source_and_mode_can_be_verified(fixture):assert describe(fixture)['status']=='verified'
def test_changed_live_helper_invalidates_qualification(fixture):
 _,_,_,_,package,_=fixture;p=package/'backends/native/cooperative_finite_stop.py';p.write_bytes(p.read_bytes()+b'\n# changed after prior proof\n');assert describe(fixture)['status']=='discovered'
def test_runtime_mode_change_invalidates_qualification(fixture):
 fixture[0].cooperative_finite_stop_probe_enabled=False;assert describe(fixture)['status']=='discovered'
@pytest.mark.parametrize('fault',['helper','engine','adapter','missing_helper','missing_hash','missing_proof_flags','missing_registration_flags','flag_false','flag_int','flag_string','both_off_finite','runtime','asset','forged_status'])
def test_stale_or_incomplete_proof_is_not_advertised(fixture,fault):
 b,e,p,save,package,_=fixture
 if fault in ['helper','engine','adapter']:
  f=package/{'helper':'backends/native/cooperative_finite_stop.py','engine':'core/engine.py','adapter':'backends/native/adapter.py'}[fault];f.write_bytes(f.read_bytes()+b'\n# changed\n')
 elif fault=='missing_helper':(package/'backends/native/cooperative_finite_stop.py').unlink()
 elif fault=='missing_hash':e['source_sha256'].pop('runtime_implementation');p['source_sha256'].pop('runtime_implementation')
 elif fault=='missing_proof_flags':p.pop('execution_runtime_flags')
 elif fault=='missing_registration_flags':e.pop('execution_runtime_flags');p.pop('execution_runtime_flags')
 elif fault=='flag_false':b.cooperative_finite_stop_probe_enabled=False
 elif fault=='flag_int':b.cooperative_finite_stop_probe_enabled=1
 elif fault=='flag_string':b.cooperative_finite_stop_probe_enabled='true'
 elif fault=='both_off_finite':b.cooperative_finite_stop_probe_enabled=False;e['execution_runtime_flags']['cooperative_finite_stop']=False;p['execution_runtime_flags']['cooperative_finite_stop']=False
 elif fault=='runtime':p['runtime_revision']='other-sdk'
 elif fault=='asset':p['asset_sha256']='other-asset'
 elif fault=='forged_status':e['status']='verified';p['source_sha256']['clip']='wrong'
 save();r=describe(fixture);assert r['status']=='discovered'and r['evidence']is None

def test_legacy_profile_can_verify_with_mode_off_if_proven(fixture):
 b,e,p,save,_,_=fixture;b.cooperative_finite_stop_probe_enabled=False;e['cooperative_finite_cycle']=False;e['execution_runtime_flags']['cooperative_finite_stop']=False;p['execution_runtime_flags']['cooperative_finite_stop']=False;save();assert describe(fixture)['status']=='verified'
