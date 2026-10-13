"""Recook only target helpers when the verified event timeline is unchanged."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import ffrenv
import ffbe_target_camera

work=Path(os.environ['FFR_CAMERA_WORK'])
assets=ROOT/'build/visions_mod/assets'
read=lambda p: json.loads(p.read_text(encoding='utf-8-sig'))
ops=[]
old_jobs=read(work/'plans.json')
jobs=read(work/'step1-plans.json')
is_target=lambda e: e['set'].get('NativeParticipantCamera_Shot') in ('targets_pan','targets_zoom')
for job in jobs:
    job['plan']=ffbe_target_camera.direct(job['plan'],job['vision'])
    previous=next(j['plan'] for j in old_jobs if j['skill']==job['skill'])
    assert job['plan']['duration']==previous['duration']
    assert [e for e in job['plan']['events'] if not is_target(e)]==[e for e in previous['events'] if not is_target(e)]
    assert [e['time'] for e in job['plan']['events'] if is_target(e)]==[e['time'] for e in previous['events'] if is_target(e)]
    functions=read(work/'cooked'/str(job['skill'])/'seqdump.json')
    for event in job['plan']['events']:
        values=event['set']
        if values.get('NativeParticipantCamera_Shot') not in ('targets_pan','targets_zoom'): continue
        matches=[k.split(':')[0] for k,v in functions.items() if isinstance(v,dict) and v.get('NativeParticipantCamera_Shot')==values['NativeParticipantCamera_Shot']]
        assert len(matches)==1,(job['skill'],values)
        ops.append({'asset':job['asset'],'export':matches[0],'set':values})
assert len(ops)==118
patch=work/'target-helpers-patch.json'
patch.write_text(json.dumps({'legacyRoot':str(assets),'outRoot':str(assets),'bytecode':ops},indent=2)+'\n')
subprocess.run([*ffrenv.FFRDT,'patch',str(patch),'--usmap',ffrenv.USMAP],check=True)
(work/'plans.json').write_text(json.dumps(jobs,indent=2)+'\n')
print('Recooked 118 target helpers; event timelines unchanged.')
