"""Losslessly retimestamp encoded frames onto their measured wall clock.

No interpolation or speed claims: the player holds each captured frame until
its next measured timestamp. Original simulation-time footage is preserved.
"""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'.runtime/video_deps'))

def export(directory,name='raw_video.mp4',stamp_name='video_timestamps.jsonl'):
    import av
    directory=Path(directory)
    stamps=[json.loads(line) for line in (directory/stamp_name).open()]
    if len(stamps)<3:raise ValueError('at least three measured video timestamps required')
    if [r['frame'] for r in stamps]!=list(range(len(stamps))):raise ValueError('noncontiguous frame IDs')
    wall=[r['wall_time']-stamps[0]['wall_time'] for r in stamps]
    if any(b<=a for a,b in zip(wall,wall[1:])):raise ValueError('wall clock must increase monotonically')
    tail=statistics.median(b-a for a,b in zip(wall[-31:],wall[-30:]))
    def at(i):
        if i<0:return i*(wall[1]-wall[0])
        if i>=len(wall):return wall[-1]+(i-len(wall)+1)*tail
        return wall[i]
    source=directory/name;destination=directory/(source.stem+'_wallclock.mp4')
    count=0;timebase=Fraction(1,90000);packet_hashes=[]
    with av.open(str(source)) as incoming,av.open(str(destination),'w',options={'movflags':'+faststart'}) as outgoing:
        video=incoming.streams.video[0];fps=video.average_rate
        output=outgoing.add_stream_from_template(video);output.time_base=timebase
        for packet in incoming.demux(video):
            if packet.pts is None:continue
            packet_hashes.append(hashlib.sha256(bytes(packet)).hexdigest())
            presentation=round(packet.pts*packet.time_base*fps)
            decode=round(packet.dts*packet.time_base*fps)
            if not 0<=presentation<len(stamps):raise ValueError('video packets do not match recorded frame IDs')
            packet.pts=round(at(presentation)/timebase)
            packet.dts=round(at(decode)/timebase)
            packet.duration=max(1,round((at(decode+1)-at(decode))/timebase))
            packet.time_base=timebase;packet.stream=output
            outgoing.mux(packet);count+=1
    if count!=len(stamps):raise ValueError(f'packet count {count} differs from measured count {len(stamps)}')
    with av.open(str(destination)) as check:
        hashes=[hashlib.sha256(bytes(p)).hexdigest() for p in check.demux(video=0) if p.pts is not None]
    if hashes!=packet_hashes:raise ValueError('encoded packets changed during remux')
    probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_packets',
                          '-show_entries','packet=pts_time','-of','json',str(destination)],capture_output=True,text=True,check=True)
    actual=sorted(float(p['pts_time']) for p in json.loads(probe.stdout)['packets'])
    error=max(abs(a-b) for a,b in zip(actual,wall))
    if len(actual)!=len(wall) or error>2/90000:raise ValueError('retimed packet timestamps failed independent verification')
    report={'source':name,'timestamps':stamp_name,'output':destination.name,'frames':count,
            'measured_wall_duration_s':wall[-1],'source_sim_duration_s':stamps[-1]['sim_time']-stamps[0]['sim_time'],
            'max_packet_timestamp_error_s':error,'method':'stream-copy VFR remux; captured frames held for measured wall intervals; no interpolation',
            'encoded_packets_unchanged':True,
            'last_frame_duration_s':tail,'last_frame_duration_note':'estimated from median final 30 intervals',
            'dependency':{'PyAV':av.__version__}}
    destination.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');parser.add_argument('--video',default='raw_video.mp4')
    parser.add_argument('--timestamps',default='video_timestamps.jsonl');args=parser.parse_args()
    print(json.dumps(export(args.directory,args.video,args.timestamps),indent=2))
