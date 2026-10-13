"""Compose the new Studio mod with retained addons, excluding retired trials."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/devui')]
import ffrenv
import addon_install

WORK = ROOT / 'build/converted-moves-test'
RETIRED = ('zzzzz_FFBE_Universal_Test_4_P', 'zzzzz_FFBE_Universal_Test_5_P',
           'zzzzz_FFBE_Universal_Test_6_P', 'zzzzzzz_FFBE_CastCamera_9_P')


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    paks = Path(ffrenv.game_paks()); mods = paks / '~mods'
    removed = [stem + ext for stem in RETIRED for ext in ('.utoc', '.ucas', '.pak') if (mods / (stem + ext)).exists()]
    replacements = {f'zzz_{ffrenv.MOD_NAME}_P{ext}': ROOT / 'build/out' / f'zzz_{ffrenv.MOD_NAME}_P{ext}'
                    for ext in ('.utoc', '.ucas', '.pak')}
    outputs, staged = addon_install.prepare(paks, replacements, print, removed=removed)
    if staged is None:
        raise ValueError('The installed private party/battle addons are required for this build')
    sources = {name: Path(staged) / 'game/FFRS/Content/Paks/~mods' / name for name in replacements}
    sources.update(outputs)
    data = {'game': str(paks.parents[2]), 'stagedGame': str(Path(staged) / 'game'),
            'before': addon_install.snapshot(mods), 'remove': removed,
            'sources': {k: str(v) for k, v in sources.items()},
            'packageHashes': {k: hashlib.file_digest(v.open('rb'), 'sha256').hexdigest() for k, v in sources.items()}}
    write(WORK / 'staged-build.json', data)
    print('Staged and verified:', staged, flush=True)


if __name__ == '__main__':
    main()
