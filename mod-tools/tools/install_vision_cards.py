"""Install the tested local vision-card package and its pinned runtime adapter."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import ffrenv

ROOT = Path(ffrenv.ROOT)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def install(game):
    game = Path(game)
    if ffrenv.game_running():
        raise RuntimeError('Close the game before installing vision cards.')
    binary = game / 'FFRS/Binaries/Win64'
    if digest(binary / ffrenv.GAME_EXE) != 'e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad':
        raise RuntimeError('This card adapter was tested only with the pinned demo build.')
    package = json.loads((ROOT / 'build/vision-cards/latest-package.json').read_text(encoding='utf-8'))
    for name, expected in package['sourceMods'].items():
        if digest(name) != expected:
            raise RuntimeError('The installed mod stack changed. Rebuild vision cards before installing.')
    for name, expected in package['files'].items():
        if digest(Path(package['package']) / name) != expected:
            raise RuntimeError('The staged card package changed after verification. Rebuild it before installing.')
    stage = ROOT / 'build/vision-cards/runtime/FFRVisionCards'
    if not (stage / 'Scripts/catalog.lua').is_file():
        raise RuntimeError('Export all card artwork before installing.')
    backup = ROOT / 'build/vision-cards' / datetime.now().strftime('install-%Y%m%d-%H%M%S')
    backup.mkdir()
    changed = []

    def copy(source, target):
        source, target = Path(source), Path(target)
        old = None
        if target.exists():
            old = backup / target.relative_to(game)
            old.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, old)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        assert digest(source) == digest(target)
        changed.append({'path': str(target), 'sha256': digest(target), 'backup': str(old) if old else None})

    runtime = binary / 'ue4ss'
    if (runtime / 'UE4SS.dll').exists() and digest(runtime / 'UE4SS.dll') != digest(ROOT / 'tools/UE4SS/ue4ss/UE4SS.dll'):
        raise RuntimeError('An incompatible UE4SS runtime is already installed; keep the staged package for review.')
    copy(ROOT / 'tools/UE4SS/dwmapi.dll', binary / 'dwmapi.dll')
    copy(ROOT / 'tools/UE4SS/ue4ss/UE4SS.dll', runtime / 'UE4SS.dll')
    if not (runtime / 'UE4SS-settings.ini').exists():
        copy(ROOT / 'tools/UE4SS/ue4ss/UE4SS-settings.ini', runtime / 'UE4SS-settings.ini')
    destination = runtime / 'Mods/FFRVisionCards'
    copy(stage / 'Scripts/catalog.lua', destination / 'Scripts/catalog.lua')
    for script in (ROOT / 'src/ffr-vision-cards').glob('*.lua'):
        if script.name != 'probe.lua':
            copy(script, destination / 'Scripts' / script.name)
    copy(ROOT / 'build/vision-cards/native/Release/main.dll', destination / 'dlls/main.dll')
    for source in Path(package['package']).iterdir():
        copy(source, game / 'FFRS/Content/Paks/~mods' / source.name)
    mods = runtime / 'Mods/mods.txt'
    existing = mods.read_text(encoding='utf-8-sig') if mods.exists() else ''
    lines = [line for line in existing.splitlines() if not line.strip().startswith('FFRVisionCards :')]
    lines.append('FFRVisionCards : 1')
    staged = backup / 'mods.txt'
    staged.write_text('\n'.join(lines)+'\n', encoding='utf-8')
    copy(staged, mods)
    record = {'game': str(game), 'package': package['package'], 'files': changed,
              'artwork': str(ROOT / 'data/vision_cards'), 'backup': str(backup)}
    (backup / 'installed.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    (ROOT / 'build/vision-cards/installed.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('Installed vision cards:', game)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', default=ffrenv.detect_game())
    args = parser.parse_args()
    install(args.game)
