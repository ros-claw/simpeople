"""Offline scrubber of measured roots; never generates replacement simulation evidence."""
import argparse
import html
import json
import os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TEMPLATE=r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SimPeople 实测轨迹</title>
<style>body{font:15px system-ui;margin:0;color:#172a39;background:#edf2f5}main{max-width:1250px;margin:auto;padding:24px}h1{font-size:24px;margin:0 0 10px}p{line-height:1.6}section{background:white;padding:18px;border-radius:10px;margin-top:16px}.grid{display:grid;grid-template-columns:3fr 1fr;gap:16px}canvas{width:100%;background:#f7f9fa;border:1px solid #d6e0e7}button,select{padding:8px;border:1px solid #a7bac7;background:white;border-radius:5px;color:#172a39}input[type=range]{width:65%}pre{white-space:pre-wrap;font:13px ui-monospace;line-height:1.6}.flags{max-height:280px;overflow:auto}.flags button{display:block;margin:6px 0;text-align:left;width:100%}a{color:#17658c}small{color:#536d7d}@media(max-width:800px){.grid{grid-template-columns:1fr}}</style>
<main><h1 id="title"></h1><p>实际人物根轨迹，按仿真时间采样回放。胶囊告警用于定位复核；本图不代表精确 mesh 接触，也不替代原始录像。</p><section id="stats"></section>
<section><button id="play">播放</button> <input id="time" type="range" min="0" value="0" step="1"> <span id="clock"></span> <label>人物 <select id="actor"><option value="">全部</option></select></label></section>
<div class="grid"><section><canvas id="map" width="950" height="790"></canvas><small>彩色点为实测根位置，细线为已走轨迹；浅色标记为语义地点示意。场景几何请查看实际视频。</small></section><section><h3>当前观测</h3><pre id="detail"></pre><h3>几何复核位置</h3><div id="flags" class="flags"></div><p id="links"></p></section></div></main>
<script type="application/json" id="data">__DATA__</script><script>
const D=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id),C=$('map'),ctx=C.getContext('2d');let n=0,playing=false,stamp=0,selected='';
$('title').textContent=D.run_id+' · 实测轨迹';$('time').max=D.frames.length-1;
$('stats').textContent=`人物 ID ${D.actors.length} · 同时观测峰值 ${D.peak_concurrent} · 轨迹采样间隔约 ${D.sample_s.toFixed(2)} sim s · 实测 RTF ${D.rtf?.toFixed(3)??'未结束'} · 几何告警 ${D.flags.length} · 此处按仿真时间回放，实际采集速度见墙钟录像。`;
D.actors.forEach((a,i)=>{const o=document.createElement('option');o.value=i;o.textContent=a;$('actor').append(o)});
const colors=D.actors.map((_,i)=>`hsl(${(i*137.508)%360} 62% 41%)`),project=(x,y)=>[475+x*15,395-y*15];
function line(points,color,width=1){if(!points.length)return;ctx.beginPath();points.forEach((p,i)=>{const [x,y]=project(...p);i?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}
function draw(){ctx.clearRect(0,0,C.width,C.height);ctx.font='11px system-ui';ctx.fillStyle='#647b8a';for(let m=-20;m<=20;m+=5){line([[m,-22],[m,22]],'#e0e8ed');line([[-22,m],[22,m]],'#e0e8ed');const p=project(m,-22);ctx.fillText(m+'m',p[0],p[1]+14)}
D.places.forEach(p=>{const [x,y]=project(...p.position);ctx.fillStyle='#b8c8d1';ctx.fillRect(x-3,y-3,6,6);if(selected!==''){ctx.fillStyle='#6a7e8c';ctx.fillText(p.name,x+4,y-4)}});
D.actors.forEach((a,i)=>{if(selected!==''&&+selected!==i)return;const trail=[];for(let j=Math.max(0,n-90);j<=n;j++){const p=D.frames[j].actors.find(p=>p[0]===i);if(p)trail.push([p[1],p[2]])}line(trail,colors[i],selected===''?1:2)});
const f=D.frames[n];f.actors.forEach(p=>{const i=p[0],[x,y]=project(p[1],p[2]);ctx.fillStyle=colors[i];ctx.globalAlpha=selected===''||+selected===i?1:.2;ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();ctx.globalAlpha=1;ctx.fillStyle='#193245';if(D.actors.length<=30||selected!==''&&+selected===i)ctx.fillText(D.actors[i].replace('person_',''),x+7,y-6)});
$('time').value=n;$('clock').textContent=f.time.toFixed(2)+' sim s';const obs=f.actors.filter(p=>selected===''||+selected===p[0]);$('detail').textContent=obs.slice(0,selected===''?7:1).map(p=>D.actors[p[0]]+'\n  x '+p[1].toFixed(2)+'  y '+p[2].toFixed(2)+' m\n  '+p[3]).join('\n\n')+(selected===''&&obs.length>7?'\n… 可选择单个人物':'');}
$('time').oninput=()=>{n=+$('time').value;draw()};$('actor').onchange=()=>{selected=$('actor').value;draw()};$('play').onclick=()=>{playing=!playing;$('play').textContent=playing?'暂停':'播放';stamp=0};function animate(t){if(playing){if(!stamp)stamp=t;if(t-stamp>=D.sample_s*1000){n=(n+1)%D.frames.length;stamp=t;draw()}}requestAnimationFrame(animate)};
D.flags.forEach(f=>{const b=document.createElement('button');b.textContent=(f.sim_time??f.start_sim_time).toFixed(2)+' s · '+(f.kind??f.issue)+' '+(f.actors??[f.actor_id]).join(' / ');b.onclick=()=>{const time=f.sim_time??f.start_sim_time;n=D.frames.reduce((best,x,i)=>Math.abs(x.time-time)<Math.abs(D.frames[best].time-time)?i:best,0);draw()};$('flags').append(b)});
D.links.forEach(l=>{const a=document.createElement('a');a.href=l.href;a.textContent=l.label;$('links').append(a,document.createElement('br'))});draw();requestAnimationFrame(animate);
</script></html>'''

def build(directory,stride=15):
 d=Path(directory).resolve();frames=[];actors=[];indices={};group=[];when=None;number=0
 for line in (d/'trajectories.jsonl').open():
  r=json.loads(line)
  if when is not None and r['sim_time']!=when:
   if number%stride==0:frames.append({'time':round(when,5),'actors':group})
   number+=1;group=[]
  when=r['sim_time'];aid=r['actor_id']
  if aid not in indices:indices[aid]=len(actors);actors.append(aid)
  if r.get('ready'):group.append([indices[aid],round(r['position_m'][0],4),round(r['position_m'][1],4),r.get('action','')])
 if group:frames.append({'time':round(when,5),'actors':group})
 if len(frames)<2:raise ValueError('not enough measured frames')
 metrics=json.loads((d/'metrics.json').read_text()) if (d/'metrics.json').exists() else {}
 sem=json.loads((d/'scene_semantics.json').read_text());places=[]
 for name,s in sem.items():
  if s.get('slots_m'):
   places.extend({'name':name+str(i),'position':p[:2]} for i,p in enumerate(s['slots_m']))
  elif 'position_m' in s:places.append({'name':name,'position':s['position_m'][:2]})
 flags=[]
 for file in ['quality_audit.json','live_geometry_audit.json']:
  if (d/file).exists():flags=json.loads((d/file).read_text())['flags'];break
 if not flags and (d/'acceptance_summary.json').exists():
  proxy=json.loads((d/'acceptance_summary.json').read_text())['trajectory_proxies']
  flags=[{'kind':'sustained_root_overlap',**f,'sim_time':f['start_sim_time']} for f in proxy['sustained_overlap_segments']]+proxy['root_discontinuities']
 out=ROOT/'reports/viewers'/f'{d.name}.html';out.parent.mkdir(parents=True,exist_ok=True)
 names=[('raw_video_wallclock.mp4','墙钟录像（含实际停顿）'),('raw_video.mp4','仿真帧录像'),('events.jsonl','原始事件'),('acceptance_summary.json','验收与性能'),('metrics.json','测量汇总')]
 links=[{'href':os.path.relpath(d/file,out.parent),'label':label} for file,label in names if (d/file).exists()]
 data={'run_id':d.name,'actors':actors,'peak_concurrent':max(len(f['actors']) for f in frames),'frames':frames,'sample_s':frames[1]['time']-frames[0]['time'],'places':places,'flags':flags,'rtf':metrics.get('rtf'),'links':links}
 out.write_text(TEMPLATE.replace('__DATA__',json.dumps(data,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')))
 return out
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--stride',type=int,default=15);a=p.parse_args();print(build(a.directory,a.stride))
