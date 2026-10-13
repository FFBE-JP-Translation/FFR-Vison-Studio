"""Repack an existing verified NPC build after changing only training stats."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/private')]
import ffrenv
from make_npc_battles import TRAINING_HP_MAX, TRAINING_STAT_MAX, TRAINING_FORM, STEM, pack_config
from npc_assets import dt, run, dump

work = Path(json.loads((ROOT/'build/npc-battles/latest.json').read_bytes())['work'])
patch_path = work/'patch.json'
patch = json.loads(patch_path.read_bytes())
for table in patch['tables']:
    if table['asset'].endswith('/Unit/DT_UnitParameter'):
        row = next(x for x in table['set'] if x['row']=='Private_Battles_'+TRAINING_FORM)
        row['set'].update(MaxHitPoint=TRAINING_HP_MAX, Defence=TRAINING_STAT_MAX, Mind=TRAINING_STAT_MAX)
dump(patch_path, patch)
dt('patch', patch_path)
dt('rows', work/'assets/FFRS/Content/Datatable/Unit/DT_UnitParameter.uasset', work/'verified/Unit/DT_UnitParameter.json')
run([ffrenv.RETOC, 'to-zen', '--version', 'UE5_6', work/'assets', work/'package'/(STEM+'.utoc')])
pack_config(work, work/'package')
if ffrenv.game_running(): raise RuntimeError('Game must be closed before updating the dummy.')
mods=Path(ffrenv.game_paks())/'~mods'
record_path=ROOT/'build/converted-moves-test/installation.json'
record=json.loads(record_path.read_text(encoding='utf-8-sig'))
backup=ROOT/'build/converted-moves-test/dummy-first-build'
backup.mkdir(exist_ok=True)
for path in (work/'package').iterdir():
    target=mods/path.name
    if not (backup/path.name).exists(): shutil.copy2(target,backup/path.name)
    shutil.copy2(path,target)
    with target.open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').hexdigest()
    with path.open('rb') as stream: assert actual==hashlib.file_digest(stream,'sha256').hexdigest()
    record['packageHashes'][path.name]=actual
record['trainingDummy']={'hp':TRAINING_HP_MAX, 'defence':TRAINING_STAT_MAX, 'spirit':TRAINING_STAT_MAX}
dump(record_path,record)
# Keep the staged candidate and its receipts usable for reproducible rebuilds.
stage_path=ROOT/'build/converted-moves-test/staged-build.json'
stage=json.loads(stage_path.read_bytes())
for name in [STEM+ext for ext in ('.pak','.utoc','.ucas')]:
    shutil.copy2(work/'package'/name,Path(stage['sources'][name]))
    stage['packageHashes'][name]=record['packageHashes'][name]
dump(stage_path,stage)
for path in (work/'verification.json', ROOT/'build/npc-battles/latest.json'):
    receipt=json.loads(path.read_bytes())
    receipt['trainingDummy']=record['trainingDummy']
    for name in [STEM+ext for ext in ('.pak','.utoc','.ucas')]:
        receipt['files'][name]={'bytes':(work/'package'/name).stat().st_size,'sha256':record['packageHashes'][name]}
    dump(path,receipt)
print('Updated the dummy to native stat caps.',flush=True)
