"""Refresh retained private addons against the candidate Studio install first."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os
import ffrenv

ADDONS = (('zzzz_PrivateParty_2_P', 'make_party_mod.py', ['--keep-saves']),
          ('zzzz_PrivateBattles_3_P', 'make_npc_battles.py', []),
          ('zzzzzz_VisionCards_7_P', '../make_vision_card_mod.py', []))


def snapshot(folder):
    result = {}
    for path in sorted(Path(folder).glob('*')):
        if path.is_file():
            with path.open('rb') as stream: result[path.name] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def run(command, log):
    process = subprocess.Popen(command, cwd=ffrenv.ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', env=dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1'))
    for line in process.stdout: log(line.rstrip())
    if process.wait(): raise RuntimeError('Retained addon rebuild failed; the installed game was left unchanged.')


def prepare(paks, replacements, log=print, removed=()):
    """Return addon outputs only after isolated builds and cooked grant checks pass."""
    paks = Path(paks).resolve(); mods = paks/'~mods'
    present = [a for a in ADDONS if any((mods/(a[0]+ext)).is_file() for ext in ('.utoc', '.ucas', '.pak'))]
    if not present: return {}, None
    for stem, script, _ in present:
        if not all((mods/(stem+ext)).is_file() for ext in ('.utoc', '.ucas', '.pak')):
            raise RuntimeError(f'{stem}: incomplete retained addon. Repair it before installing.')
        if not (Path(ffrenv.ROOT)/'tools/private'/script).is_file():
            raise RuntimeError('The retained party/battle addons require their local builders. Open Studio Local to install.')
    before = snapshot(mods)
    work = Path(ffrenv.ROOT)/'build/addon-installs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    staged = work/'game/FFRS/Content/Paks'; staged_mods = staged/'~mods'
    staged_mods.mkdir(parents=True)
    for source in paks.iterdir():
        if source.is_file(): (staged/source.name).symlink_to(source.resolve())
    skipped = {stem+ext for stem,_,_ in ADDONS for ext in ('.utoc','.ucas','.pak')} | set(removed)
    for source in mods.iterdir():
        if source.is_file() and source.name not in skipped | set(replacements):
            shutil.copy2(source, staged_mods/source.name)
    for name, source in replacements.items(): shutil.copy2(source, staged_mods/name)
    game = work/'game'
    spec = Path(ffrenv.ROOT)/'build/visions_mod/units-built.json'
    if spec.is_file(): shutil.copy2(spec, work/'units-built.json')
    with (work/'build.log').open('w', encoding='utf-8') as stream:
        def note(line):
            stream.write(line+'\n'); stream.flush(); log(line)
        for index, (stem, script, args) in enumerate(present, 1):
            label = ('Refreshing vision cards and their Mitra shop' if 'VisionCards' in stem else
                     'Refreshing Raegen and Helena' if 'Party' in stem else 'Refreshing the Mitra battle NPC')
            note(f'##stage {label} ({index} of {len(present)})')
            run([*ffrenv.py(str(Path(ffrenv.ROOT)/'tools/private'/script)), '--game', str(game), '--install', *args], note)
        if replacements:
            note('##stage Checking abilities and level unlocks')
            run([*ffrenv.py(str(Path(ffrenv.ROOT)/'tools/private/verify_vision_install.py')),
                 '--game', str(game), '--out', str(work/'verification.json'), '--spec', str(work/'units-built.json')], note)
    if ffrenv.game_running(): raise RuntimeError('The game was opened during preparation. Close it and install again.')
    if snapshot(mods) != before: raise RuntimeError('Installed mods changed during preparation. Install again to include their latest versions.')
    output = {stem+ext: staged_mods/(stem+ext) for stem,_,_ in present for ext in ('.utoc','.ucas','.pak')}
    (work/'prepared.json').write_text(json.dumps({'game': str(paks.parents[2]), 'before': before,
        'outputs': {k:str(v) for k,v in output.items()}}, indent=2), encoding='utf-8')
    return output, str(work)
