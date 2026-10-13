"""Update the stationary cast blend without rebuilding source media or tables."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import make_vision_mod as builder
import ffbe_cast_camera
units = json.loads((ROOT/'build/cast-camera-step1/units.json').read_text(encoding='utf-8'))
edits=[]
for unit in units:
    for sid, recipe in unit['skills'].items():
        seq=ffbe_cast_camera.sequence_id(int(sid),recipe)
        path=ROOT/'build/visions_mod'/f'SEQ_Battle_{seq}_Master-events.json'
        events=json.loads(path.read_text(encoding='utf-8'))
        assert not any(e['set']['EventType']=='NativeGroundApproach' for e in events['bytecode'])
        for event in events['bytecode']:
            if event['set']['EventType']!='NativeParticipantCamera': continue
            event['set']['NativeParticipantCamera_Frame']=10
            edits.append(event)
        path.write_text(json.dumps(events,ensure_ascii=False),encoding='utf-8')
out=ROOT/'build/cast-camera-step1/stationary-blends.json'
out.write_text(json.dumps({'legacyRoot':builder.OUT,'outRoot':builder.OUT,'bytecode':edits}),encoding='utf-8')
builder.run([*builder.FFRDT,'patch',str(out),'--usmap',builder.USMAP])
print(f'Smoothed {len(edits)} stationary casting blends.')
