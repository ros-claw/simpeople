"""Generate a frozen 45-s diagnostic from the reviewed shared benchmark.

The original 600-s case, fixture and shared helpers remain unchanged. This
script launches no Native/model process and never pauses another process.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


HARNESS_SHA256 = '8045c0de23ca6d10cf97714cd8d549f79c27a105962214a3b7cc0f3e0dfbc2d9'


def generate(shared, trace_source):
    shared = Path(shared).resolve(); trace_source = Path(trace_source).resolve()
    original = shared/'scripts/bench_native_runtime.py'
    if hashlib.sha256(original.read_bytes()).hexdigest() != HARNESS_SHA256:
        raise ValueError('shared benchmark changed; re-review before generating')
    code = original.read_text()
    patches = [
        ('ROOT=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser();',
         'ROOT=Path('+repr(str(shared))+');p=argparse.ArgumentParser();'),
        ("p.add_argument('--diagnostic-idle-tags',choices=['default','basic','disabled'],default='default')\n",
         "p.add_argument('--diagnostic-idle-tags',choices=['default','basic','disabled'],default='default')\n"
         "p.add_argument('--arrival-recovery',choices=['off','on'],required=True)\n"),
        ("if case:(harness/'case.json').write_text(json.dumps(case,indent=2)+'\\n')\n",
         "if case:(harness/'case.json').write_text(json.dumps(case,indent=2)+'\\n')\n"
         "assert case and case['case_id']=='release_narrow_30_seed17_v2' and case['duration_s']==600\n"
         "assert len(case['actors'])==30 and len(case['requests'])==60 and not case.get('events') and not case.get('checkpoints') and not case.get('stop_when_complete')\n"
         "shutil.copy2("+repr(str(trace_source))+",harness/'arrival_prefix_trace.py')\n"),
        ('engine=journal=recorder=bridge=monitor=None;code=0',
         'engine=journal=recorder=bridge=monitor=arrival_trace=None;code=0'),
        ('    if not args.lifecycle:backend.enable_corridor_profile()\n',
         "    backend.arrival_recovery_probe_enabled=args.arrival_recovery=='on'\n"
         '    if not args.lifecycle:backend.enable_corridor_profile()\n'),
        ("    journal.write('asset_manifest.json',backend.assets)\n    class Client:",
         "    trace_module=load(harness/'arrival_prefix_trace.py','simpeople_arrival_prefix_trace')\n"
         "    arrival_trace=trace_module.ArrivalPrefixTrace(backend,engine,out)\n"
         "    journal.write('arrival_prefix_config.json',{'diagnostic_prefix':True,'duration_s':45,'original_case_duration_s':case['duration_s'],'enabled':backend.arrival_recovery_probe_enabled,'case_input_sha256':hashlib.sha256(Path(args.case).read_bytes()).hexdigest(),'original_harness_sha256':"+repr(HARNESS_SHA256)+"})\n"
         "    journal.write('asset_manifest.json',backend.assets)\n    class Client:"),
        ("duration=30 if args.lifecycle else case['duration_s'];replay=", 'duration=45;replay='),
        ('journal.sample(engine,identity)\n', 'journal.sample(engine,identity);arrival_trace.sample(identity)\n'),
        ("        if case.get('finite',True) and not matches_expectations():code=2\n",
         '        # A45s prefix is not a grade of the original600s workload.\n'),
        ("'functional_expected_matched':matches_expectations() if replay else True,\n",
         "'functional_expected_matched':None,'whole_workload_functional_expected_matched':matches_expectations() if replay else None,\n"
         "        'diagnostic_prefix':True,'arrival_recovery_enabled':backend.arrival_recovery_probe_enabled,\n"),
        ('    if recorder:recorder.close()\n', '    if recorder:recorder.close()\n    if arrival_trace:arrival_trace.close()\n'),
    ]
    for before, after in patches:
        if code.count(before) != 1:
            raise ValueError('unexpected shared harness integration point: '+before[:80])
        code = code.replace(before, after)
    ast.parse(code)
    return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--shared-workspace', required=True)
    parser.add_argument('--trace-source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args(); target = Path(args.output)
    if target.exists(): raise ValueError('keep prior probe versions; use a new output path')
    target.write_text(generate(args.shared_workspace, args.trace_source))
    print(json.dumps({'probe': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                      'duration_s': 45, 'original_case_duration_s': 600, 'native_launched': False}))
