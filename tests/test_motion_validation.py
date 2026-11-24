import hashlib
import numpy as np
import pytest
from simpeople.core.errors import SimPeopleError
from simpeople.motion.validation import validate_artifact


def artifact_at(directory):
    poses=np.zeros((50,1,7),dtype=np.float32);poses[:,:,6]=1
    arrays={'corrected':{'local_poses':poses,'foot_contacts':np.zeros((50,4),dtype=np.float32)},
        'raw_decoded':{'local_poses':poses},'raw_network':{'features':np.zeros((1,64,366),dtype=np.float32),'num_tokens':np.array([14],dtype=np.int32)}}
    a={'schema_version':'simpeople.motion-asset.v1','rig_sha256':'a'*64,'frames':50,'sample_rate':30,'native_execution_verified':False,'retarget_verified':False}
    for name,data in arrays.items():
        path=directory/(name+'.npz');np.savez(path,**data);a[name]={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return a


@pytest.mark.parametrize('damage',['hash','escape','nan','tokens','execution_claim'])
def test_untrusted_asset_cannot_pass_on_manifest_alone(tmp_path,damage):
    directory=tmp_path/'owned';directory.mkdir();a=artifact_at(directory);rig={'rig_sha256':'a'*64,'joint_names':['Hips']}
    assert validate_artifact(a,rig,directory)['passed']
    if damage=='hash':a['corrected']['sha256']='0'*64
    if damage=='escape':
        outside=tmp_path/'outside.npz';outside.write_bytes((directory/'corrected.npz').read_bytes());a['corrected']['path']=str(outside)
    if damage in {'nan','tokens'}:
        key='corrected' if damage=='nan' else 'raw_network';path=directory/(key+'.npz')
        with np.load(path,allow_pickle=False) as data:arrays={k:data[k] for k in data.files}
        if damage=='nan':arrays['local_poses'][0,0,0]=np.nan
        else:arrays['num_tokens'][0]=6
        np.savez(path,**arrays);a[key]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    if damage=='execution_claim':a['native_execution_verified']=True
    with pytest.raises(SimPeopleError) as error:validate_artifact(a,rig,directory)
    assert error.value.code=='MOTION_INVALID_ARTIFACT'
