"""Cook one Studio-imported converted unit without changing the selected roster."""
import os
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get('FFR_SMOKE_WORK', str(ROOT / 'build/converted-moves-test/import-build'))).resolve()
if not WORK.is_relative_to(ROOT / 'build'):
    raise ValueError('Smoke output must be inside the workspace build directory')
os.environ['FFR_UNIT_SPEC'] = str(WORK.parent / 'new-unit-smoke.json')
os.environ['FFR_MOD_STEM'] = 'zzz_ConvertedImportSmoke_P'
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tools/devui'))
import effect_downloads
with open(os.environ['FFR_UNIT_SPEC'], encoding='utf-8') as source:
    effect_downloads.ensure_loadout(json.load(source), lambda **info: print(info.get('stage', 'Preparing effects'), flush=True))
import make_vision_mod as build

build.BUILD = str(WORK)
build.OUT = str(WORK / 'assets')
sys.argv = [sys.argv[0], '--no-install']
build.main()
