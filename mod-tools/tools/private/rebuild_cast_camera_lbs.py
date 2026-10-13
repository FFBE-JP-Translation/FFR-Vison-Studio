"""Recook only the four LB sequences after a camera timing adjustment."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import make_vision_mod as builder
import ffbe_resonance

WORK = ROOT/'build/cast-camera-step1'
units = json.loads((WORK/'units.json').read_text(encoding='utf-8'))
patch = json.loads((ROOT/'build/visions_mod/patch.json').read_text(encoding='utf-8'))
tables = {t['asset']:deepcopy(t) for t in patch['tables']}
for asset, table_data in tables.items():
    table_data['add'] = ([r for r in table_data.get('add', [])
                          if r.get('set', {}).get('ID') in (444010,444020,444030,444040)]
                         if asset.endswith('/Skill/DT_SkillData') else [])
    table_data['set'] = []
def table(rel): return tables[builder.DT+rel]
clones, jobs = [], []
for unit in units:
    builder.prepare_ffbe_resonance(unit, dict(unit['lb_custom'], resonance=True),
                                  440000+(unit['id']-13099)*10, table, clones, jobs)
clone_patch = WORK/'lb-clones.json'
clone_patch.write_text(json.dumps({'legacyRoot':builder.LEGACY, 'outRoot':builder.OUT,
                                  'clones':clones}), encoding='utf-8')
builder.run([*builder.FFRDT, 'patch', str(clone_patch), '--usmap', builder.USMAP])
for job in jobs:
    ffbe_resonance.build(job, builder.OUT, builder.BUILD, builder.FFRDT, builder.USMAP, builder.run)
(WORK/'lb-plans.json').write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding='utf-8')
print('Recooked four LB camera timelines; tables and ordinary commands were retained.')
