"""Measure cold/warm addon artwork preparation without installing anything."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/private')]
import make_party_mod as party
import npc_assets
import make_npc_battles as battles


def hashes(folder):
    result = {}
    for path in folder.rglob('*'):
        if path.is_file():
            with path.open('rb') as stream:
                result[str(path.relative_to(folder))] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, default=ROOT/'build/studio-beta/20260928-b1/engine')
    parser.add_argument('--out', type=Path, default=ROOT/'build/install-ux-benchmark')
    args = parser.parse_args()
    beta = args.engine
    source = Path(json.loads((beta/'build/party-members/latest.json').read_text())['work'])
    enemy = Path(json.loads((beta/'build/npc-battles/latest.json').read_text())['work'])
    work = args.out
    native = {kind: json.loads((source/f'rain-{kind}.json').read_text(encoding='utf-8-sig'))
              for kind in ('battle', 'menu')}
    picker = ROOT/'build/ffbe-boss-picker/Enemy Sources'
    # Use the same imported enemy sources recorded by the local beta.
    if not picker.exists():
        picker = next((beta/'build').glob('*/Enemy Sources'))
    report = {}
    for label in ('cold', 'warm'):
        phase = work/label
        if phase.exists(): raise ValueError(f'Benchmark output already exists: {phase}')
        assets = phase/'assets'; assets.mkdir(parents=True)
        started = time.perf_counter()
        for unit in party.UNITS:
            party.build_sprite(unit, source/'legacy', assets, phase, native)
            party.build_portraits(unit, source/'legacy', assets, phase)
        for index, (form, _) in enumerate(battles.ENEMIES):
            npc_assets.build_boss_sprite(picker/form, form, 9461+index, phase, enemy/'legacy', assets)
        report[label] = {'seconds': round(time.perf_counter()-started, 3), 'files': hashes(assets)}
        print(label, report[label]['seconds'], flush=True)
    if report['cold']['files'] != report['warm']['files']:
        raise ValueError('Reused artwork differs from newly prepared artwork')
    prior = {**hashes(source/'assets'), **hashes(enemy/'assets')}
    for name, digest in report['warm']['files'].items():
        if prior.get(name) != digest: raise ValueError(f'Artwork differs from accepted install: {name}')
    report['byteIdenticalToInstalledArtwork'] = True
    report['installedIntoGame'] = False
    (work/'verified.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('ARTWORK CACHE VERIFIED', flush=True)


if __name__ == '__main__': main()
