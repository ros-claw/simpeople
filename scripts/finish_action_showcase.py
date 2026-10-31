"""A labeled view of the actual native audition; no synthetic motion frames."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from check_master import check
from finish_shift_change import COLOR_FILTER,COLOR_ARGS

ROOT=Path(__file__).resolve().parents[1]


def finish(run_id,output,music):
    d=ROOT/'runs'/run_id;out=Path(output);out.mkdir(exist_ok=True,parents=True)
    audit=json.loads((d/'custom_action_audit.json').read_text());assert audit['passed']
    cast=json.loads((d/'cinematic_cast.json').read_text());registry=json.loads((d/'custom_actions/registry.json').read_text())
    labels=[registry[r['actor_id']]['label'] for r in cast]
    ass=out/'SimPeople_Action_Showcase_zh-CN.ass'
    text='''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Label,Noto Sans CJK SC,42,&H00F7F5EF,&H000000FF,&H00201812,&H90000000,0,0,0,0,100,100,0,0,1,2,1,8,60,60,50,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    for i,label in enumerate(labels):
        a=i*3;b=a+3
        text+=f'Dialogue: 0,0:00:{a:02d}.00,0:00:{b:02d}.00,Label,,0,0,0,,{label}'+r'\N{\fs22}原生 Behavior 动作 · 同一片场实录'+'\n'
    text+='Dialogue: 0,0:00:24.00,0:00:30.00,Label,,0,0,0,,动作结束，恢复行走'+r'\N{\fs22}ROSClaw SimPeople · 仿真时间回放'+'\n'
    assert not ass.exists();ass.write_text(text)
    movie=out/'SimPeople_Action_Showcase_30s_1080p30.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-filter_threads','4','-n','-i',str(d/'raw_video.mp4'),'-i',str(music),
        '-map','0:v:0','-map','1:a:0','-vf',COLOR_FILTER+',ass='+str(ass),'-af','afade=t=out:st=28:d=2','-t','30',
        '-c:v','libx264','-crf','18','-preset','slow','-threads','4','-pix_fmt','yuv420p','-fps_mode','passthrough',
        *COLOR_ARGS,'-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart',str(movie)],check=True)
    result={'run_id':run_id,'frame_policy':'all 900 original consecutive source frames, no interpolation or duplication',
            'audit':audit,'check':check(movie,frames=900),'source_sha256':hashlib.sha256((d/'raw_video.mp4').read_bytes()).hexdigest()}
    assert result['check']['passed'];(out/'action_showcase_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(movie)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--output',required=True);p.add_argument('--music',required=True)
    a=p.parse_args();finish(a.run_id,a.output,a.music)
