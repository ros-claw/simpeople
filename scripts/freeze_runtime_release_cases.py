"""Freeze18 release inputs from two observed scenes; no native acceptance claim."""
import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from freeze_workloads import freeze_population
from simpeople.core.workloads import validate_case,case_hash
from runtime_fixture_points import fixture_points


def revision(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def blocked(point,boxes,margin=.45):
    return any(all(abs(point[i]-box['position'][i]) < box['size'][i]/2+margin-1e-9 for i in [0,1]) for box in boxes)


def matrix_cases(wide,narrow,seeds=(17,42,99)):
    if len(seeds)!=3 or len(set(seeds))!=3 or any(isinstance(s,bool) or not isinstance(s,int) or not 0<=s<2**31 for s in seeds):
        raise ValueError('exactly three distinct nonnegative31-bit trace seeds required')
    layout=narrow.get('t2_narrow_layout',{})
    if layout.get('revision') not in {'floor_spanning_door_v1','floor_spanning_door_release_v2'} or not layout.get('wall_boxes'):
        raise ValueError('observed floor-spanning narrow layout required')
    revised=layout['revision']=='floor_spanning_door_release_v2'
    narrow_id='industrial_narrow_release_v2' if revised else 'industrial_narrow_probe_v1'
    version=2 if revised else 1
    boxes=layout['wall_boxes'];result=[]
    for name,semantics,scene_id in [('wide',wide,'industrial'),('narrow',narrow,narrow_id)]:
        for people in [10,30,50]:
            for seed in seeds:
                case=freeze_population(semantics,people,cycles=2,seed=seed)
                case['case_id']=f'release_{name}_{people}_seed{seed}_v{version}';case['scene']={'id':scene_id,'revision':revision(semantics)}
                adjustments=[]
                def location(point,label):
                    original=list(point);current=list(point)
                    if name=='narrow' and blocked(current,boxes):
                        # Explicit input projection, never a runtime teleport.
                        # Keep the original side; x==0 has a fixed east tie-break.
                        current[0]=math.copysign(1.25,current[0]) if current[0] else 1.25
                        if blocked(current,boxes):raise ValueError('cannot form a safe grid-aligned narrow input: '+label)
                        adjustments.append({'input':label,'original_m':original,'mapped_m':current,'reason':'observed wall plus0.45m navigation clearance'})
                    return current
                for actor in case['actors']:
                    actor['spawn_anchor']=location(actor['spawn_anchor'],'spawn:'+actor['actor_id'])
                for request in case['requests']:
                    request.update(expected_outcome='succeeded',think_s=0)
                    for index,step in enumerate(request['steps']):
                        target=step.get('target')
                        if isinstance(target,list):step['target']=location(target,request['request_case_id']+':step'+str(index))
                        elif isinstance(target,str):
                            if target not in semantics:raise ValueError('unknown semantic target: '+target)
                            semantic=semantics[target]
                            candidates=[semantic['position_m']] if 'position_m' in semantic else semantic.get('slots_m',[])
                            if name=='narrow' and any(blocked(p,boxes) for p in candidates):
                                raise ValueError('semantic target requires an independently revised scene: '+target)
                validate_case(case)
                # Include seat approaches, every queue slot and BOTH exits.
                # A safe target centre cannot establish a safe interaction.
                if name=='narrow':
                    for point in fixture_points(case,semantics):
                        if blocked(point['position_m'],boxes):
                            raise ValueError('semantic navigation point requires an independently revised scene: '+point['use'])
                result.append({'case':case,'input_adjustments':adjustments,'people':people,'seed':seed,'layout':name,
                               'native_fixture_preflight_required':True,'nominal_feasibility_verified':False})
    assert len(result)==18
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--wide-semantics',required=True);p.add_argument('--narrow-semantics',required=True);p.add_argument('--output',required=True);args=p.parse_args()
    wide_path=Path(args.wide_semantics).resolve();narrow_path=Path(args.narrow_semantics).resolve();wide=json.load(open(wide_path));narrow=json.load(open(narrow_path));rows=matrix_cases(wide,narrow);out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=False);manifest=[]
    for row in rows:
        case=row['case'];f=out/(case['case_id']+'.json');f.write_text(json.dumps(case,indent=2)+'\n');manifest.append({k:v for k,v in row.items() if k!='case'}|{'case_id':case['case_id'],'case_sha256':case_hash(case),'file_sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'requests':len(case['requests'])})
    (out/'matrix_manifest.json').write_text(json.dumps({'schema_version':'simpeople.runtime-release-inputs.v1','cases':manifest,'scene_sources':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [wide_path,narrow_path]},'generator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'runtime_versions_frozen':False,'scope':'18input cases ONLY, not executions or proof of nominal feasibility. Identical case files must be replayed on original Baseline-B0 and one final candidate after native fixture validation.600s/two cycles/20,60,100 requests; prior failed runs unchanged.'},indent=2)+'\n');print('FROZEN_RELEASE_INPUT_CASES',len(rows))


if __name__=='__main__':main()
