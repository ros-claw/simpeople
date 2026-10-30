import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime,timezone
from simpeople.core.errors import SimPeopleError
from simpeople.core.protocol import identifier
from simpeople.core.modes import PROFILES,resolve_mode
from .client import call
from .doctor import DEFAULT_ISAAC, doctor

ROOT=Path(os.environ.get('SIMPEOPLE_ROOT',Path(__file__).resolve().parents[3])).resolve()

def main():
    parser=argparse.ArgumentParser(prog='simpeople',description='ROSClaw SimPeople: real Isaac Behavior control')
    sub=parser.add_subparsers(dest='command',required=True)
    d=sub.add_parser('doctor');d.add_argument('--isaac-dir',default=os.environ.get('SIMPEOPLE_ISAAC_DIR',DEFAULT_ISAAC))
    d.add_argument('--output',default=str(ROOT/'reports'))
    c=sub.add_parser('call');c.add_argument('method');c.add_argument('--json',default='{}');c.add_argument('--file')
    c.add_argument('--endpoint',default=os.environ.get('SIMPEOPLE_ENDPOINT','http://127.0.0.1:8768'))
    for name in ['run','serve']:
        r=sub.add_parser(name)
        r.add_argument('--isaac-dir',default=os.environ.get('SIMPEOPLE_ISAAC_DIR',DEFAULT_ISAAC))
        r.add_argument('--scenario',choices=['single_life_cycle','walk_run_stop','industrial_life','asset_pool_validation','appearance_contact_sheet','native_avoidance','gait_quality_validation'],default='single_life_cycle')
        r.add_argument('--people',type=int,default=1);r.add_argument('--seed',type=int,default=42)
        r.add_argument('--asset-id',default='default')
        r.add_argument('--gpu',type=int,default=3);r.add_argument('--port',type=int,default=8768)
        r.add_argument('--duration',type=float,default=None);r.add_argument('--no-video',action='store_true')
        r.add_argument('--mode',choices=list(PROFILES),default='generation')
        r.add_argument('--width',type=int);r.add_argument('--height',type=int)
        r.add_argument('--allow-unverified',action='store_true',help='explicit capability discovery; does not mark acceptance passed')
        r.add_argument('--realtime',action='store_true');r.add_argument('--run-id')
        r.add_argument('--visible',action='store_true')
        r.add_argument('--camera',choices=['overview','follow','seat_side','gait_side'],default='overview')
        r.add_argument('--traffic-profile',choices=['native','segmented','corridor'],default='segmented')
        r.add_argument('--quality-audit',action='store_true')
        r.add_argument('--capture-profile',choices=['full','no_encode','render_only','none'],default='full')
        r.add_argument('--warmup-wall-s',type=float,default=30)
        r.add_argument('--measure-wall-s',type=float)
        r.add_argument('--performance-profile',choices=['baseline','optimized'],default='optimized')
        r.add_argument('--tracy',action='store_true')
        r.add_argument('--encoder-threads',type=int,choices=range(0,33))
    i=sub.add_parser('inspect');i.add_argument('--run-id',required=True)
    sub.add_parser('mcp')
    args=parser.parse_args()
    try:
        if args.command=='doctor':result=doctor(args.isaac_dir,args.output)
        elif args.command=='call':result=call(args.method,json.loads(Path(args.file).read_text() if args.file else args.json),args.endpoint)
        elif args.command=='inspect':
            directory=ROOT/'runs'/args.run_id
            if directory.parent!=ROOT/'runs':raise ValueError('invalid run_id')
            result={p.name:json.loads(p.read_text()) for p in directory.glob('*.json') if p.name in {'metrics.json','config.json','acceptance.json','ready.json'}}
        elif args.command=='mcp':
            from .mcp_server import main as mcp_main
            mcp_main();return
        else:
            for key,value in resolve_mode(args.mode,args.width,args.height,args.quality_audit).items():setattr(args,key,value)
            args.run_id=identifier(args.run_id or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8],'run_id')
            command=[str(Path(args.isaac_dir)/'python.sh'),'-u',str(ROOT/'scripts/kit_main.py'),
                '--scenario',args.scenario,'--people',str(args.people),'--seed',str(args.seed),
                '--gpu',str(args.gpu),'--port',str(args.port),'--width',str(args.width),'--height',str(args.height),
                '--camera',args.camera,'--asset-id',args.asset_id]
            if args.command=='serve':command.append('--serve')
            for name in ['no_video','allow_unverified','realtime','visible','quality_audit','tracy']:
                if getattr(args,name):command.append('--'+name.replace('_','-'))
            for name in ['duration','run_id','traffic_profile','capture_profile','warmup_wall_s','measure_wall_s','performance_profile','encoder_threads','mode']:
                if getattr(args,name) is not None:command.extend(['--'+name.replace('_','-'),str(getattr(args,name))])
            from .launch import run_logged
            raise SystemExit(run_logged(command,ROOT,args.run_id))
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    except (SimPeopleError,ValueError,OSError) as e:
        print(json.dumps({'error':e.as_dict() if isinstance(e,SimPeopleError) else {'code':'CLI_ERROR','message':str(e)}},ensure_ascii=False))
        raise SystemExit(1)

if __name__=='__main__':main()
