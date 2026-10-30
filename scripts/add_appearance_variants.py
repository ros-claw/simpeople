"""Create per-instance apparel tint variants; geometry and rig remain identical."""
import copy
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1];path=root/'configs/assets.json'
config=json.loads(path.read_text());originals=[a for a in config['assets'] if not a.get('appearance_tint')]
palette=[[.07,.42,.50],[.85,.32,.07],[.12,.25,.57],[.17,.42,.17],[.60,.22,.23],[.43,.31,.16]]
default={'asset_id':'default','base_identity_id':'behavior_default','appearance_id':'default',
         'source_uri':str(root/'assets/cache/behavior/Characters/Human/Default.usd'),
         'content_hash':hashlib.sha256((root/'assets/cache/behavior/Characters/Human/Default.usd').read_bytes()).hexdigest(),
         'rig_id':'Human','backend_support':['native'],'verified_actions':['walk','run','wait','look_at','sit','leave_seat'],
         'radius_m':.35,'height_m':1.82,'motion_library':str(root/'assets/cache/behavior/MotionLibrary/Human/HumanMotionLibrary.usd'),
         'license_note':'NVIDIA Behavior sample; local reference only','dependency_status':'runtime_loaded'}
variants=[]
for i,base in enumerate([default]+originals):
    variant=copy.deepcopy(base)
    variant.update(asset_id=base['asset_id']+'_accent',appearance_id='apparel_accent',
                   appearance_tint=palette[i%len(palette)],appearance_status='discovered',
                   motion_verification_inherited_from=base['asset_id'])
    variants.append(variant)
config['assets']=originals+variants
path.write_text(json.dumps(config,indent=2))
print(json.dumps({'base_identities':len(originals)+1,'registered_appearances':len(originals)+len(variants)+1}))
