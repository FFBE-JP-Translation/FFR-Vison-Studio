"""Apply camera-kit table edits over the installed tables, preserving other mods."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import ffrenv
from verify_mod import equivalent

BASELINE = ROOT/'build/cast-camera-step1'
WORK = Path(os.environ.get('FFR_CAMERA_WORK') or BASELINE)
ASSETS = ROOT/'build/visions_mod/assets'
STEM = 'zzzzzzz_FFBE_CastCamera_9_P'

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path, value): Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
def run(args):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, encoding='utf-8')
    if result.returncode: raise RuntimeError(result.stdout+result.stderr)
    return result.stdout
def digest(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()
def rows(folder, asset, label):
    output = WORK/'merge-readback'/(label+'-'+Path(asset).name+'.json')
    output.parent.mkdir(exist_ok=True)
    path = folder/(asset+'.uasset')
    if not path.is_file(): return {}
    mapping = output.with_suffix('.usmap')
    shutil.copy2(ffrenv.USMAP, mapping)
    run([*ffrenv.FFRDT, 'rows', path, output, '--usmap', mapping])
    return read(output)['rows']

def stage():
    selection_path = WORK/'focused-selection.json'
    selection = read(selection_path) if selection_path.is_file() else {}
    retired = set(selection.get('retiredSkills', []))
    if selection.get('retainCheckpointAssets'):
        archive = ROOT/selection['retainCheckpointAssets']
        prefix = 'build/visions_mod/assets/'
        copied = []
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                if member.is_dir() or not member.filename.startswith(prefix): continue
                relative = member.filename[len(prefix):]
                target = (ASSETS/relative).resolve()
                if not target.is_relative_to(ASSETS.resolve()): raise ValueError('Checkpoint asset escaped candidate output')
                if not target.exists():
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(z.read(member)); copied.append(relative)
        write(WORK/'retained-camera-assets.json',copied)
    source = read(WORK/'patch.json' if (WORK/'patch.json').exists() else ROOT/'build/visions_mod/patch.json')
    tables = deepcopy(source['tables'])
    def load(t): return t['asset'], rows(BASELINE/'installed-legacy', t['asset'], 'before')
    with ThreadPoolExecutor(max_workers=4) as pool: before = dict(pool.map(load, tables))
    # retoc does not descend into ~mods. Refuse a base-only snapshot even when
    # it parses perfectly: these are required parts of this installed copy.
    native_units = before['FFRS/Content/Datatable/Unit/DT_UnitParameter']
    native_ids = {r['ID'] for r in native_units.values()}
    if not {9461,9462,9463,9464,9465,9466,13500,13501,13502,13503} <= native_ids:
        raise ValueError('Installed snapshot is missing addon rows; extract the flat baseline-paks folder including all mods')
    units = read(WORK/'units.json')
    owned = {int(s) for u in units for s in u['skills']} | retired
    for table in tables:
        live = before[table['asset']]
        retired_names = set()
        if table['asset'].endswith('/Skill/DT_SkillData'):
            for name, row in live.items():
                if row.get('ID') in retired:
                    retired_names.add(name)
                    table.setdefault('set', []).append({'row':name, 'set':{
                        'belongCommandList':[], 'commandIdBelongDebuggingAllSkills':[-1,-1]}})
        def identity(r): return (r.get('ID'), r.get('Level'))
        new = {identity(a['set']): a['row'] for a in table.get('add', []) if 'ID' in a['set']}
        names = {a['row'] for a in table.get('add', [])}
        table['remove'] = [name for name, r in live.items()
                           if identity(r) in new and name not in names]
        for edit in table.get('set', []):
            if edit['row'] in retired_names: continue
            # A replacement can introduce a new row and then refine its values
            # (for example the source LB hit weights). There is no installed
            # array to preserve for that row; leave its explicit edit intact.
            if edit['row'] not in live and edit['row'] in names: continue
            old = live[edit['row']]
            for key, value in edit['set'].items():
                if not isinstance(value, list): continue
                if key == 'ItemList':
                    merged = deepcopy(old[key])
                    for item in value:
                        if item['ItemId'] not in {u['id'] for u in units}: continue
                        match = next((i for i,r in enumerate(merged) if r['ItemId']==item['ItemId']), None)
                        if match is None: merged.append(item)
                        else: merged[match] = item
                    edit['set'][key] = merged
                else:
                    edit['set'][key] = value + [v for v in old.get(key, []) if v not in value
                        and not (key == 'equipperActionVisionSkills' and v in owned)]
    # Only tables are recooked here; the verified sequence and audio assets stay intact.
    patch = {'legacyRoot': str(BASELINE/'installed-legacy'), 'outRoot': str(ASSETS), 'tables': tables}
    write(WORK/'merge-patch.json', patch)
    run([*ffrenv.FFRDT, 'patch', WORK/'merge-patch.json', '--usmap', ffrenv.USMAP])
    def check(table):
        asset = table['asset']; after = rows(ASSETS, asset, 'after')
        changed = {e['row'] for kind in ('add', 'set') for e in table.get(kind, [])} | set(table['remove'])
        untouched = {k:v for k,v in before[asset].items() if k not in changed}
        for name, row in untouched.items():
            if name not in after or not equivalent(row, after[name]):
                raise ValueError('Retained mod row changed: '+asset+'/'+name)
        return {'asset': asset, 'retainedRowsVerified': len(untouched), 'editedRows': len(changed)}
    with ThreadPoolExecutor(max_workers=4) as pool: report = list(pool.map(check, tables))
    write(WORK/'retained-mods-verification.json', report)
    print('Preserved', sum(r['retainedRowsVerified'] for r in report), 'existing rows across', len(report), 'tables', flush=True)
    env = dict(os.environ, FFR_MOD_STEM=STEM)
    subprocess.run([sys.executable, str(ROOT/'tools/build_mod.py'), str(ASSETS), 'CastCamera_9'], env=env, check=True)
    game = Path(ffrenv.game_root()); paks = game/'FFRS/Content/Paks'
    staged = BASELINE/'game/FFRS/Content/Paks'; (staged/'~mods').mkdir(parents=True, exist_ok=True)
    # Hard links stay on the source volume only where available; the staged
    # directory contains links to immutable inputs, never modified by these tools.
    for path in paks.iterdir():
        if path.is_file():
            dest = staged/path.name
            if not dest.exists():
                try: dest.symlink_to(path)
                except OSError: os.link(path, dest)
    import shutil
    for path in (paks/'~mods').iterdir():
        if path.is_file(): shutil.copy2(path, staged/'~mods'/path.name)
    for ext in ('.pak', '.utoc', '.ucas'):
        shutil.copy2(ROOT/'build/out'/(STEM+ext), staged/'~mods'/(STEM+ext))
    write(WORK/'stage.json', {'game': str(game), 'stagedGame': str(BASELINE/'game'),
        'before': {p.name:digest(p) for p in (BASELINE/'baseline-paks').iterdir()
                   if p.is_file() and p.name.startswith('z')},
        'candidate': {STEM+ext:digest(ROOT/'build/out'/(STEM+ext)) for ext in ('.pak','.utoc','.ucas')}})

if __name__ == '__main__': stage()
