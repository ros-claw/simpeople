"""Synthetic startup/body counterexamples, not Native qualification."""
import copy
import math
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from audit_canonical_startup_rejection import review
from test_canonical_heading_rejection_audit import fixture as heading_fixture
from test_motion_startup_domain import fixture as startup_fixture


def fixture():
 rows,ref,r=heading_fixture();actual,domain=startup_fixture()
 for x in rows:
  x['actual_observation']['facing_direction']=[0,1,0]
  x['world_pose']=copy.deepcopy(ref['world_pose'])
 r['actual_observation']=copy.deepcopy(rows[3]['actual_observation'])
 ref['native_startup_conditions']=domain
 bad=copy.deepcopy(actual);bad['response_random_offset_s']=.01
 r.update(startup_settings_before=actual,startup_settings_bad=bad,startup_settings_restored=copy.deepcopy(actual),
   supported_entry_quality={'passed':True,'native_entry_domain':{'passed':True}})
 r['error']['details']={'startup_error':{'passed':False,'observed_settings':copy.deepcopy(bad),'required_domain':domain,
   'errors':['native setting outside declared startup domain: response_random_offset_s']}}
 return rows,ref,r


def test_supported_body_and_heading_can_refuse_only_changed_startup_without_mutating_owner():
 result=review(*fixture());assert result['verified'],result
 assert result['owned_body_readback']['actual_post_rejection_samples']==31


@pytest.mark.parametrize('fault',['other_epoch','missing_seed','numeric_provenance','two_settings_changed',
 'not_restored','different_error','invented_bad_readback','no_supported_entry','wrong_heading',
 'boolean_jitter','nonfinite_response','domain_jitter_boolean'])
def test_receipt_alone_does_not_prove_a_live_startup_refusal(fault):
 rows,ref,r=fixture()
 if fault=='other_epoch':r['after']['control_epoch']=4
 elif fault=='missing_seed':r['startup_settings_before']['seed_configuration']=None
 elif fault=='numeric_provenance':r['startup_settings_before']['seed_configuration']['configured_before_agents']=1
 elif fault=='two_settings_changed':r['startup_settings_bad']['response_time_s']=.3
 elif fault=='not_restored':r['startup_settings_restored']['response_random_offset_s']=.01
 elif fault=='different_error':r['error']['details']['startup_error']['errors']=['body mismatch']
 elif fault=='invented_bad_readback':r['error']['details']['startup_error']['observed_settings']['response_random_offset_s']=.02
 elif fault=='no_supported_entry':r['supported_entry_quality']['passed']=False
 elif fault=='wrong_heading':rows[0]['actual_observation']['facing_direction']=[math.sin(.01),math.cos(.01),0]
 elif fault=='boolean_jitter':r['startup_settings_before']['response_random_offset_s']=False
 elif fault=='nonfinite_response':r['startup_settings_bad']['response_time_s']=float('inf')
 else:ref['native_startup_conditions']['response_random_offset_s']=False
 assert not review(rows,ref,r)['verified']
