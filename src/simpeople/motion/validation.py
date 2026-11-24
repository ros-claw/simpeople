"""Inspect generated assets; passing these checks does not authorize execution."""
import hashlib
from pathlib import Path
import zipfile
from simpeople.core.errors import SimPeopleError
from .rig import validate_poses


def validate_artifact(artifact,rig_contract,workspace):
    import numpy as np
    def reject(message):raise SimPeopleError('MOTION_INVALID_ARTIFACT',message,stage='validation')
    if artifact.get('schema_version')!='simpeople.motion-asset.v1':reject('unsupported artifact schema')
    if artifact.get('rig_sha256')!=rig_contract['rig_sha256']:reject('artifact rig revision mismatch')
    frames=artifact.get('frames')
    if isinstance(frames,bool) or not isinstance(frames,int) or not 18<=frames<=58 or artifact.get('sample_rate')!=30:reject('invalid model sample range or rate')
    if artifact.get('native_execution_verified') is not False or artifact.get('retarget_verified') is not False:reject('model worker cannot certify native execution')
    root=Path(workspace).resolve();loaded={};checks={}
    for kind in ('corrected','raw_decoded','raw_network'):
        ref=artifact.get(kind,{})
        try:
            path=Path(ref['path']).resolve(strict=True)
            if not path.is_relative_to(root):reject('artifact escapes its owned workspace')
            if path.stat().st_size>256_000_000:reject('artifact file exceeds size limit')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=ref['sha256']:reject('artifact content hash mismatch')
            with zipfile.ZipFile(path) as z:
                if sum(x.file_size for x in z.infolist())>256_000_000:reject('expanded artifact exceeds size limit')
            with np.load(path,allow_pickle=False) as data:arrays={k:data[k] for k in data.files}
            if not arrays or any(a.dtype.kind not in 'fiu' or not np.isfinite(a).all() for a in arrays.values()):reject('artifact contains non-numeric or non-finite arrays')
        except (KeyError,ValueError,OSError,zipfile.BadZipFile) as error:reject(str(error))
        if kind!='raw_network':
            try:poses=validate_poses(arrays['local_poses'],len(rig_contract['joint_names']))
            except (KeyError,ValueError) as error:reject(str(error))
            if len(poses)!=frames:reject('artifact frame count mismatch')
            if kind=='corrected':
                contacts=arrays.get('foot_contacts')
                if contacts is None or contacts.shape!=(frames,4) or np.any((contacts<0)|(contacts>1)):reject('invalid four-foot-contact channels')
            loaded[kind]=poses
        else:
            features=arrays.get('features');tokens=arrays.get('num_tokens')
            if features is None or features.ndim!=3 or features.shape[0]!=1 or tokens is None or tokens.shape!=(1,) or tokens.dtype.kind not in 'iu':reject('invalid raw FP32 N=1 network envelope')
            if not 6<=int(tokens[0])<=16 or int(tokens[0])*4-6!=frames:reject('raw token count disagrees with decoded frames')
        checks[kind]={'sha256':ref['sha256'],'bytes':path.stat().st_size}
    correction=float(np.max(np.linalg.norm(loaded['corrected'][:,:,:3]-loaded['raw_decoded'][:,:,:3],axis=-1)))
    return {'passed':True,'frames':frames,'sample_rate':30,'files':checks,'max_endpoint_correction_m':correction,
        'native_execution_verified':False,'retarget_verified':False}
