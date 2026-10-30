"""Publish queryable quality records only from successful closed native audits."""
import argparse,json,sys
from pathlib import Path
from pxr import Usd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.core.quality_catalog import SCHEMA,hash_tree,template_hash
from simpeople.backends.native.seat_geometry import seat_geometry_hash
p=argparse.ArgumentParser();p.add_argument('--seat-run',required=True);p.add_argument('--gait-run',required=True);a=p.parse_args()
seatdir=ROOT/'runs'/a.seat_run;gaitdir=ROOT/'runs'/a.gait_run
assert json.loads((seatdir/'seat_acceptance.json').read_text())['passed']
seat=json.loads((seatdir/'seat_quality.json').read_text());assert seat['rigs_sampled']==12 and seat['rigs_without_vertex_penetration']==12 and seat['fine_all_available']
gait=json.loads((gaitdir/'gait_pool_acceptance.json').read_text());assert gait['passed'] and len(gait['results'])==12
gait_quality=json.loads((gaitdir/'gait_pool_quality.json').read_text());assert gait_quality['all_contacts_measured'] and len(gait_quality['rigs'])==12
assets={x['asset_id']:x for x in json.loads((seatdir/'asset_manifest.json').read_text())}
sem=json.loads((seatdir/'scene_semantics.json').read_text());stage=Usd.Stage.Open(str(seatdir/'stage.usda'),load=Usd.Stage.LoadNone)
records=[];cache={}
def revision(directory):
 path=str(directory)
 if path not in cache:cache[path]=hash_tree(directory)
 return cache[path]
for aid,row in seat['actors'].items():
 asset=assets[aid];seatdef=sem[row['seat']];geometry=seat_geometry_hash(stage,seatdef);assert geometry
 common={'asset_revision_sha256':revision(Path(asset['source_uri']).parent),'motion_revision_sha256':revision(Path(asset['motion_library']).parent),'rig_id':asset['rig_id'],'runtime_revision':asset['quality_runtime_revision']}
 assert all(common.values())
 records.append({**common,'kind':'seat','seat_template_sha256':template_hash(seatdef['seat_profile']),'seat_geometry_sha256':geometry,
                 'status':'verified_vertex_audit','asset_id_at_audit':aid,'evidence_run':a.seat_run,'minimum_vertex_clearance_m':row['skinned_vertex_min_m'],
                 'scope':'full seat cycle and cancellation windows; selected actual head/neck skinned vertices; surrounding scene and every triangle are not certified'})
 if any(x['asset_id']==aid and x['terminal']=='succeeded' for x in gait['results']):
  records.append({**common,'kind':'locomotion','status':'measured_contact_proxy','asset_id_at_audit':aid,'evidence_run':a.gait_run,
                  'traffic_profile':'corridor','walk_speed_mps':1.2,'run_speed_mps':2.8,'scope':'native walk/jog completion plus calibrated contact-proxy measurements; not a no-slip certificate'})
result={'schema_version':SCHEMA,'records':records,'resource_hash_scope':'all USD layers under each local asset and motion directory; texture edits do not invalidate geometric fit',
        'placement_scope':'seat-local geometry; scene obstacles and arbitrary external chairs require separate checks'}
(ROOT/'configs/quality_catalog.json').write_text(json.dumps(result,indent=2));print('quality records',len(records))
