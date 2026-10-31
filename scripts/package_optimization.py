"""Package thin plugins and allowlisted numeric evidence, without licensed assets."""
import argparse,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPORTS=['reports/OPTIMIZATION_20261031.md','reports/optimization_1031_gates.json','reports/optimization_1031_results.json','reports/optimization_1031_claude_status.json','configs/quality_catalog.json','reports/optimization_1031_plugin_installation.json','reports/optimization_1031_assets/media_manifest.json','reports/optimization_1031_launcher_validation.json','reports/optimization_1031_final_performance.json']
REPORTS+=['reports/optimization_1031_performance.json','reports/optimization_1031_optional_performance.json','reports/optimization_1031_interactive_performance.json','reports/optimization_1031_assets/report_sources.json']
REPORTS+=['reports/optimization_1031_assets/seat_before.png','reports/optimization_1031_assets/seat_after.png']
REPORTS+=['reports/optimization_1031_assets/crowd50_media_manifest.json']
RUNS=['opt1031-motion-A-native-02','opt1031-motion-B-segmented-01','opt1031-motion-C-corridor-01','opt1031-motion-CD-corridor-02','opt1031-motion-CD-lazy-03',
      'opt1031-seat-baseline-12-01','opt1031-seat-calibrated-12-01','opt1031-seat-calibrated-v3-12-01','opt1031-seat-calibrated-v3-12-02',
      'opt1031-gait-corridor-12-01','opt1031-gait-corridor-12-02','opt1031-host-codex-01','opt1031-host-codex-02',
      'opt1031-regression50-seed17-01','opt1031-regression50-seed17-02','opt1031-regression50-seed17-03','opt1031-cleanup-corridor-13-01','opt1031-cleanup-corridor-13-02','opt1031-final30-cpu16-01','opt1031-final30-retrace01-01',
      'opt1031-final30-full-01','opt1031-final30-no-encode-01','opt1031-final30-render-only-01','opt1031-final30-trace-01','opt1031-final30-trace-02','opt1031-final30-trace-03','opt1031-final30-trace-04','opt1031-final30-retrace01-02','opt1031-final30-retrace01-03','opt1031-final30-full-02']
RUNS+=['opt1031-interactive10-01']+['opt1031-perf30-0'+str(i)+'-'+capture for i,capture in enumerate(['full','no-encode','render-only','none','full','full'],1)]
NAMES=['manifest.json','framing_audit.json','runtime_settings.json','runtime_settings_end.json','mcp_ownership_acceptance.json','config.json','completion.json','metrics.json','acceptance_summary.json','gait_quality.json','motion_acceptance.json','seat_quality.json','seat_acceptance.json',
       'gait_pool_acceptance.json','gait_pool_quality.json','host_acceptance.json','cleanup_acceptance.json','recording_metrics.json','observation_counters.json','profile_summary.json','trace_metadata.json','native_controller_lease_check.json','quality_audit.json']
def write_zip(path,files):
 if path.exists():raise ValueError('preserve existing package; choose a new label')
 hashes={}
 with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
  for f,name in files:
   is_report_figure=str(f.relative_to(ROOT)) in {'reports/optimization_1031_assets/seat_before.png','reports/optimization_1031_assets/seat_after.png'}
   if f.is_symlink() or (f.suffix not in {'.json','.md','.toml','.txt',''} and not is_report_figure):raise ValueError('non-source/numeric file '+str(f))
   data=f.read_bytes();hashes[name]=hashlib.sha256(data).hexdigest();z.writestr(name,data)
  z.writestr('PACKAGE_MANIFEST.json',json.dumps({'files':hashes,'scope':'numeric acceptance evidence, two rendered report figures, or thin host package; no model/texture asset data or private host sessions'},indent=2))
 return {'path':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'files':len(hashes)}
p=argparse.ArgumentParser();p.add_argument('--label',default='0.2.0-preview');a=p.parse_args()
out=ROOT/'dist';out.mkdir(exist_ok=True);packages=[]
for host in ('codex','claude'):
 base=ROOT/'plugins'/host
 files=[(f,str(f.relative_to(base))) for f in sorted(base.rglob('*')) if f.is_file()]
 packages.append(write_zip(out/f'simpeople-{host}-{a.label}.zip',files))
files=[(ROOT/name,name) for name in REPORTS if (ROOT/name).is_file()]
for run in RUNS:
 base=ROOT/'runs'/run
 for name in NAMES:
  f=base/name
  if f.is_file():files.append((f,str(f.relative_to(ROOT))))
 for f in sorted((base/'gait_quality').glob('*.json')):files.append((f,str(f.relative_to(ROOT))))
packages.append(write_zip(out/f'simpeople-evidence-summary-{a.label}.zip',files))
manifest=out/f'simpeople-optimization-delivery-{a.label}.json';manifest.write_text(json.dumps({'packages':packages},indent=2));print(manifest.read_text())
