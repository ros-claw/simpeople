"""Offline install inspection. Live binding catalog is captured by native bench."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from simpeople.tools.runtime_contract import capture_runtime_contract
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--isaac-dir',default='/data/omniverse/isaac-sim-6.2.0');a=p.parse_args()
    result=capture_runtime_contract(ROOT,a.output,a.isaac_dir);print(json.dumps({'isaac_version':result['isaac_version'],'live_bindings_loaded':result['readiness']['api_loaded']}))
