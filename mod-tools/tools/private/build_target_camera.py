"""Build step two from the accepted step-one timelines and installed tables."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import ffbe_resonance as sequence
import ffbe_target_camera
import make_vision_mod as builder

WORK=Path(os.environ.get('FFR_CAMERA_WORK') or ROOT/'build/target-camera-step2')
CHECKPOINT=ROOT/'checkpoints/ffbe-camera-step1'
WORK.mkdir(parents=True,exist_ok=True)
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def write(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

units=read(CHECKPOINT/'source/mods/EstherTsukiko/units.json')
removed=[]
for unit in units:
    unit.update(presentationStep='target_camera',testingMPCost=1)
    unit['step1Passives']=unit.pop('convertedPassives',{})
    entries={e['sourceKey']:e for e in unit['ffbeLibrary']}
    for sid,skill in list(unit['skills'].items()):
        entry=entries.get(skill.get('ffbe',{}).get('source'),{}); ancestry=[]
        while entry:
            ancestry.append(entry['kind']);entry=entries.get(entry.get('parent'),{})
        if 'PASSIVE' in ancestry:
            unit.setdefault('step1AutomaticActions',{})[sid]=unit['skills'].pop(sid)
            removed.append({'vision':unit['en'],'skill':int(sid),'name':skill['en']})
        else:
            skill.setdefault('set',{})['Cost']=1
            if skill.get('cameraTest'): skill['desc']=skill['desc'].replace('cost nothing','cost 1 MP')
    unit['lb_custom'].setdefault('set',{})['Cost']=1
    for field in ('awakening','synchro'):
        unit[field]=[[g for g in tier if g[0]!='PassiveSkill' and
                      (g[0]!='ActiveSkill' or str(g[1]) in unit['skills'])] for tier in unit[field]]
write(WORK/'units.json',units)
write(WORK/'units-before.json',read(CHECKPOINT/'source/mods/EstherTsukiko/units.json'))
write(WORK/'removed-automatic-actions.json',removed)
if not (WORK/'installation.json').exists():
    write(WORK/'installation.json',read(CHECKPOINT/'records/installation.json'))

patch=read(CHECKPOINT/'records/build-patch.json')
removed_ids={r['skill'] for r in removed}
retained={int(s) for u in units for s in u['skills']} | {444010,444020,444030,444040}
for table in patch['tables']:
    if table['asset'].endswith('/DT_SkillData'):
        table['add']=[r for r in table['add'] if r['set'].get('ID') not in removed_ids]
        for row in table['add']:
            if row['set'].get('ID') in retained: row['set']['Cost']=1
    if table['asset'].endswith('/DT_VisionAwakeningMasteryData'):
        for row in table['add']:
            unit=next(u for u in units if u['id']==row['set']['ID'])
            row['set']['detailData']=builder.detail(unit['awakening'][row['set']['Level']])
    if table['asset'].endswith('/DT_VisionSynchroMasteryData'):
        for row in table['add']:
            unit=next(u for u in units if u['id']==row['set']['ID'])
            row['set']['detailData']=builder.detail(unit['synchro'][row['set']['Level']])
write(WORK/'patch.json',patch)

originals=WORK/'step1-plans.json'
if not originals.exists():
    jobs=[]
    for unit in units:
        for sid in [*map(int,unit['skills']),440000+(unit['id']-13099)*10]:
            seq=sid+1 if sid<485000 else 2_000_000+sid*2
            payload=read(ROOT/f'build/visions_mod/SEQ_Battle_{seq}_Master-events.json')
            functions={int(e['export']):e['set'] for e in payload['bytecode']}
            doc=read(ROOT/f'build/visions_mod/SEQ_Battle_{seq}_Master-authored.json')
            events=[];duration=None
            for export in doc['Exports']:
                for prop in export.get('Data',[]):
                    if prop['Name']=='PlaybackRange': duration=prop['Value'][0]['Value']['UpperBound']['Value']['Value']
                    if prop['Name']!='EventChannel': continue
                    for tick,key in zip(sequence.child(prop['Value'],'KeyTimes'),sequence.child(prop['Value'],'KeyValues')):
                        while not isinstance(tick,(int,float)): tick=tick[0] if isinstance(tick,list) else tick['Value']
                        events.append({'time':tick,'set':functions[sequence.child(key['Value'],'Ptrs','Function')]})
            assert duration and events
            jobs.append({'vision':unit['id'],'skill':sid,'asset':payload['sequenceData'][0]['asset'],
                         'plan':{'events':sorted(events,key=lambda e:e['time']),'duration':duration}})
    write(originals,jobs)
jobs=read(originals)
clones=[{'from':sequence.SHELL,'to':j['asset'],
         'rename':[['SEQ_Battle_440111_Cut_000',j['asset'].split('/')[-1]]]} for j in jobs]
write(WORK/'sequence-clones.json',{'legacyRoot':builder.LEGACY,'outRoot':builder.OUT,'clones':clones})
builder.run([*builder.FFRDT,'patch',str(WORK/'sequence-clones.json'),'--usmap',builder.USMAP])
for job in jobs:
    job['plan']=ffbe_target_camera.direct(job['plan'],job['vision'])
    sequence.build(job,builder.OUT,str(WORK),builder.FFRDT,builder.USMAP,builder.run)
write(WORK/'plans.json',jobs)
print(f'Built {len(jobs)} active command timelines; all cost 1; {len(removed)} automatic actions and passive grants excluded.')
