"""Inspect installed/runtime contracts; never import Kit in controller Python."""
import hashlib,inspect,json
from pathlib import Path
from .doctor import doctor

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def capture_runtime_contract(root,output,isaac_dir='/data/omniverse/isaac-sim-6.2.0',*,backend=None,engine=None,extensions=None):
    root=Path(root);out=Path(output);out.mkdir(parents=True,exist_ok=True);environment=doctor(isaac_dir,out);catalog={}
    environment['python_process_role']='Kit runtime' if backend else 'controller/offline inspection'
    environment['runtime_probe']='runtime_contract.json (fresh bindings in this run)' if backend else 'not performed in this process'
    (out/'environment_report.json').write_text(json.dumps(environment,ensure_ascii=False,indent=2)+'\n')
    if backend is not None:
        targets={'behavior':backend.api,'navigation':backend.nav}
        if engine and engine.actors:
            actor=next(iter(engine.actors.values()))
            if backend.observe(actor['handle']).get('ready'):targets['agent']=backend.agent(actor['handle'])
        for name,obj in targets.items():
            catalog[name]={key:getattr(obj,key).__doc__ or '' for key in dir(obj) if not key.startswith('_') and callable(getattr(obj,key,None))}
    config=Path(backend.config_dir) if backend else root/'configs'
    fingerprints={'configs/'+name:sha(config/name) for name in ['assets.json','seat_profiles.json','quality_catalog.json'] if (config/name).exists()}
    asset_revisions={a['asset_id']:{k:a.get(k) for k in ['content_hash','rig_id','motion_revision_sha256','source_uri','motion_library']} for a in backend.assets} if backend else {}
    methods=catalog.get('agent',{});head=[k for k in methods if k in {'look_at','gaze_at'} or 'head' in k and ('effector' in k or 'look' in k)];hands=[k for k in methods if 'hand' in k and ('effector' in k or 'reach' in k)]
    readiness={'api_loaded':backend is not None,'timeline_playing':bool(backend.timeline.is_playing()) if backend else None,
        'navmesh_published':bool(backend.nav.get_navmesh()) if backend else None,
        'agents':{aid:bool(backend.observe(a['handle']).get('ready')) for aid,a in engine.actors.items()} if engine else {}}
    contract={'schema_version':'simpeople.runtime-contract.v1','isaac_version':environment['isaac_version'],'isaac_dir':environment['isaac_dir'],
        'environment':environment,'loaded_extensions':extensions or [],'binding_catalog':catalog,'readiness':readiness,
        'units':{'stage_meters_per_unit':backend.mpu,'stage_up_axis':str(backend.up),'public_coordinates':'Z-up metres'} if backend else None,
        'observations':{'root':'IBehaviorAgent.get_world_translation; stage-to-public conversion','joints':'IBehaviorAgent.get_joint_world_transform; mapped actual joint indices',
            'speed':'finite difference of actual root positions on the simulation clock; see observation_sim_time',
            'task_state':'IBehaviorAgent.get_task_status; reservation route state is a separate supervisor aggregate','accepted_is_completed':False},
        'gesture_bindings':{'head':head,'hand':hands,'status':'discovered_not_execution_verified' if head or hands else 'not_discovered'},
        'asset_config_hashes':fingerprints,'asset_revisions':asset_revisions,'runtime_policy':getattr(engine,'policy',None),
        'engine_source':{'path':inspect.getsourcefile(type(engine)),'sha256':sha(inspect.getsourcefile(type(engine)))} if engine else None,
        'limits':['method existence/docstrings do not certify animation, IK reachability or actor compatibility','GPU totals describe shared device load, not exclusive performance']}
    stable={k:contract[k] for k in ['isaac_version','binding_catalog','units','asset_config_hashes','asset_revisions']};contract['compatibility_sha256']=hashlib.sha256(json.dumps(stable,sort_keys=True).encode()).hexdigest()
    (out/'runtime_contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n');return contract
