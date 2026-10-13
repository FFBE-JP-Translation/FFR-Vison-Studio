"""Add four labeled, inert test commands to the already built compatible kit."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/private')]
import make_vision_mod as builder
import ffbe_audio
import ffbe_resonance
from prepare_cast_camera_kit import add_camera_tests

WORK = ROOT/'build/cast-camera-step1'
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def write(p, d): p.write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
units = read(WORK/'units.json')
patch_path = ROOT/'build/visions_mod/patch.json'
patch = read(patch_path)
tables = {}
def table(rel): return tables.setdefault(builder.DT+rel, {'asset':builder.DT+rel, 'add':[], 'set':[]})
clones, jobs = [], []
for unit in units:
    before = set(unit['skills'])
    add_camera_tests(unit)
    for sid in set(unit['skills'])-before:
        builder.prepare_native_camera_command(unit, unit['skills'][sid], int(sid), table, clones, jobs)
    mastery = next(t for t in patch['tables'] if t['asset'].endswith('/DT_VisionAwakeningMasteryData'))
    row = next(r for r in mastery['add'] if r['set']['ID']==unit['id'] and r['set']['Level']==0)
    row['set']['detailData'] = builder.detail(unit['awakening'][0])
for asset, update in tables.items():
    target = next(t for t in patch['tables'] if t['asset']==asset)
    target['add'].extend(update['add']); target['set'].extend(update['set'])
patch['clones'].extend(clones)
write(WORK/'camera-test-clones.json', {'legacyRoot':builder.LEGACY, 'outRoot':builder.OUT, 'clones':clones})
builder.run([*builder.FFRDT,'patch',str(WORK/'camera-test-clones.json'),'--usmap',builder.USMAP])
for job in jobs:
    ffbe_resonance.build(job,builder.OUT,builder.BUILD,builder.FFRDT,builder.USMAP,builder.run)
for bank in {b['name']:b for j in jobs for b in ffbe_audio.banks(j.get('audio'))}.values():
    ffbe_audio.build(bank,builder.OUT,builder.BUILD,builder.FFRDT,builder.USMAP,builder.run,builder.LEGACY)
write(patch_path,patch)
write(WORK/'units.json',units)
write(ROOT/'build/visions_mod/units-built.json',units)
print(f'Added {len(jobs)} inert camera-test commands; no damage or effect reactions are authored.')
