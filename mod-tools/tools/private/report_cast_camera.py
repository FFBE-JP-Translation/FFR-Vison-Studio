"""Summarize source coverage and measurements from isolated native battles."""
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/devui'))
import native_variants
WORK=ROOT/'build/cast-camera-step1'
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
units=read(WORK/'units.json')
kits=[]
for unit in units:
    selected={g:native_variants.strongest(unit['ffbeLibrary'],g) for g in ('abilities','bonuses')}
    tests=[s for s in unit['skills'].values() if s.get('cameraTest')]
    kits.append({'vision':unit['en'], 'activeIncludingRaegenBlast':len(unit['skills']),
                 'playableAbilities':len(unit['skills'])-len(tests), 'passives':len(unit['convertedPassives']),
                 'limitBursts':1, 'cameraTests':[s['en'] for s in tests],
                 'unimplementedPassives':[{'name':e['name'],'reasons':e.get('issues',[])}
                                          for e in selected['bonuses'] if e['status']!='ready']})
(WORK/'kit-report.json').write_text(json.dumps(kits,indent=2)+'\n',encoding='utf-8')
runs=[]
for folder in sorted((WORK/'runtime/runs').iterdir()):
    events=folder/'captures/events.jsonl'
    if not events.is_file(): continue
    state=read(folder/'run.json')
    records=[json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()]
    samples=[s for s in records if s['kind']=='sample' and 'effectiveFov' in s]
    # Earlier runs diagnosed inactive-camera readings and the half-length pan.
    if not samples or folder.name<'20260917_030110_589': continue
    assert state.get('cleaned') and not state.get('changedSaveFiles') and not state.get('changedPackages'),folder
    assert any(e['kind']=='complete' for e in records),folder
    base=samples[-1]['effectiveFov']
    zoom=max(math.tan(math.radians(base/2))/math.tan(math.radians(s['effectiveFov']/2)) for s in samples)
    assert abs(zoom-1.15)<.015,(folder,'zoom',zoom)
    assert abs(samples[-1]['effectiveRotation']['yaw'])<.1,(folder,'camera failed to restore')
    active=next(e for e in records if e['kind']=='native_command_list')
    vision=next(u for u in units if u['id']==state['vision'])
    command_ids=set(active['skills'].values())
    expected={int(s) for s in vision['skills']}
    moving=state['skill'] in (444010,444020,444030,444040)
    early=[s for s in samples if s['castElapsed']<1.5]
    if moving:
        assert max(s['caster']['y'] for s in early)-min(s['caster']['y'] for s in early)>100,folder
        assert max(s['effectiveRotation']['yaw'] for s in early)-min(s['effectiveRotation']['yaw'] for s in early)>5,folder
    runs.append({'vision':vision['en'],'skill':state['skill'],'run':folder.name,
                 'zoomFactor':round(zoom,5),'moving':moving,'restored':True,
                 'nativeKitComplete':expected<=command_ids,'nativeKitCount':len(expected&command_ids),
                 'savesUnchanged':True,'temporaryRuntimeCleaned':True})
(WORK/'runtime-verification.json').write_text(json.dumps(runs,indent=2)+'\n',encoding='utf-8')
print(json.dumps(runs,indent=2))
