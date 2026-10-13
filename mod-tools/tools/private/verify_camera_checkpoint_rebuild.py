"""Rebuild one accepted action using only the checkpoint's saved compiler and inputs."""
from datetime import datetime
import importlib.util
import json
import math
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
CP = ROOT / 'checkpoints/ffbe-camera-step2'
OUT = ROOT / 'build/checkpoint-rebuild-proof' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
OUT.mkdir(parents=True)


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def run(args):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, encoding='utf-8')
    if result.returncode: raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


for name in ('native-tools.zip', 'workspace-inputs.zip'):
    with zipfile.ZipFile(CP / 'archives' / name) as z:
        for entry in z.infolist():
            p = entry.filename
            needed = (p.startswith('src/ffr-dt/bin/Release/net8.0/') or p == 'extracted/Mappings.usmap'
                      or p.startswith('extracted/legacy/FFRS/Content/Sequencer/Battle/Skill/440110/440111/Track/SEQ_Battle_440111_Cut_000.')
                      or p == 'build/target-camera-step2-retry/plans.json')
            if needed:
                target = (OUT / p).resolve()
                assert target.is_relative_to(OUT.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(entry))

sys.path.insert(0, str(CP / 'source/tools'))
spec = importlib.util.spec_from_file_location('checkpoint_sequence', CP / 'source/tools/ffbe_resonance.py')
sequence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sequence)
job = next(j for j in read(OUT / 'build/target-camera-step2-retry/plans.json') if j['skill'] == 485203)
compiler = ['dotnet', str(OUT / 'src/ffr-dt/bin/Release/net8.0/ffr-dt.dll')]
usmap = OUT / 'extracted/Mappings.usmap'
assets = OUT / 'cooked'
patch = {'legacyRoot': str(OUT / 'extracted/legacy'), 'outRoot': str(assets),
         'clones': [{'from': sequence.SHELL, 'to': job['asset'],
                     'rename': [['SEQ_Battle_440111_Cut_000', job['asset'].split('/')[-1]]]}]}
(OUT / 'clone.json').write_text(json.dumps(patch), encoding='utf-8')
run([*compiler, 'patch', OUT / 'clone.json', '--usmap', usmap])
sequence.build(job, assets, OUT, compiler, str(usmap), run)
path = assets / (job['asset'] + '.uasset')
for verb in ('tojson', 'seqdump'):
    run([*compiler, verb, path, OUT / (verb + '.json'), '--usmap', usmap])
functions = {int(k.split(':')[0]): v for k, v in read(OUT / 'seqdump.json').items()}
observed = []
for export in read(OUT / 'tojson.json')['Exports']:
    for prop in export.get('Data', []):
        if prop['Name'] != 'EventChannel': continue
        for tick, key in zip(sequence.child(prop['Value'], 'KeyTimes'), sequence.child(prop['Value'], 'KeyValues')):
            while not isinstance(tick, (int, float)): tick = tick[0] if isinstance(tick, list) else tick['Value']
            observed.append({'time': tick, 'set': functions[sequence.child(key['Value'], 'Ptrs', 'Function')]})
observed.sort(key=lambda e: e['time'])
expected = sorted(job['plan']['events'], key=lambda e: e['time'])
assert len(observed) == len(expected)


def contains(actual, wanted):
    if isinstance(wanted, dict):
        fields = {k.lower(): v for k, v in actual.items()}
        # Cooked struct JSON elides zero/false fields and uses lower-case vector axes.
        return all(contains(fields.get(k.lower(), 0), v) for k, v in wanted.items())
    if isinstance(wanted, (float, int)) and not isinstance(wanted, bool): return math.isclose(actual, wanted, abs_tol=1e-5)
    return actual == wanted


for a, b in zip(observed, expected):
    assert contains(a, b), (b['time'], b['set']['EventType'],
                            {k: v for k, v in b['set'].items() if not contains(a['set'].get(k, 0), v)})
report = {'skill': 485203, 'name': 'Infinity', 'events': len(observed),
          'allSavedEventParametersMatch': True, 'compilerFromCheckpoint': True,
          'sourceFromCheckpoint': True, 'donorAndPlanFromCheckpoint': True,
          'gameModified': False, 'work': str(OUT)}
(ROOT / 'docs/discovery/ffbe-step3/checkpoint-rebuild-proof.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
