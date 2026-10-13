"""Check live camera projection after the target shot has settled."""
import json
import math
import os
import sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
WORK=Path(os.environ.get('FFR_CAMERA_WORK') or ROOT/'build/target-camera-step2')
def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def vec(v): return np.array([v[k] for k in ('x','y','z')])
units=read(WORK/'units.json');plans={j['skill']:j['plan'] for j in read(WORK/'plans.json')}
installed=read(WORK/'installation.json')['packageHashes']['zzzzzzz_FFBE_CastCamera_9_P.ucas']
results=[]
for folder in sorted((WORK/'runtime/runs').iterdir()):
    state=read(folder/'run.json');path=folder/'captures/events.jsonl'
    if not any(p.endswith('zzzzzzz_FFBE_CastCamera_9_P.ucas') and h==installed for p,h in state['beforePackages'].items()): continue
    if not state.get('fixtureCompleted') or len(state.get('captures',[]))!=state.get('expectedCaptureCount'): continue
    if not path.exists(): continue
    records=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    if not any(e['kind']=='complete' for e in records): continue
    assert state['cleaned'] and not state['changedSaveFiles'] and not state['changedPackages']
    unit=next(u for u in units if u['id']==state['vision'])
    skill=state['skill'];events=plans[skill]['events']
    cameras=[e for e in events if e['set']['EventType']=='NativeParticipantCamera']
    settle=(cameras[-1]['time']-cameras[0]['time'])/24000+cameras[-1]['set']['NativeParticipantCamera_Frame']/30
    samples=[e for e in records if e['kind']=='sample']
    # Native view updates and screenshot captures can differ by one tick.
    settled=[s for s in samples if settle+.08<=s['castElapsed']<=settle+.45]
    assert settled,(folder,'no settled target samples')
    selected=next(e for e in records if e['kind']=='selected_targets')['targets']
    target_count=len(selected)
    target_ids=list(samples[0]['enemies']) if target_count==2 else [str(state['enemy'])]
    boxes=[]
    for sample in settled:
        p,y=map(math.radians,(sample['effectiveRotation']['pitch'],sample['effectiveRotation']['yaw']))
        forward=np.array([math.cos(p)*math.cos(y),math.cos(p)*math.sin(y),math.sin(p)])
        right=np.array([-math.sin(y),math.cos(y),0]);up=np.cross(forward,right)
        origin=vec(sample['effectiveLocation']);tan=math.tan(math.radians(sample['effectiveFov']/2));points=[]
        for key in target_ids:
            for part in ('feet','head'):
                d=vec(sample['enemies'][key][part])-origin;z=d@forward
                points.append((.5+(d@right)/(2*tan*z),.5-(d@up)*1280/(720*2*tan*z)))
        boxes.append([min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)])
    box=np.median(boxes,axis=0).tolist()
    assert 0<box[0]<box[2]<.65 and .015<box[1]<box[3]<.97,(folder,'target framing',box)
    assert (box[0]+box[2])/2<.46 and box[3]>.70 and box[3]-box[1]>.20,(folder,'target framing too distant or centered',box)
    pan_start=(cameras[-2]['time']-cameras[0]['time'])/24000
    zoom_start=(cameras[-1]['time']-cameras[0]['time'])/24000
    hold=[s for s in samples if pan_start-.24<=s['castElapsed']<=pan_start-.07]
    pan=[s for s in samples if pan_start+.025<=s['castElapsed']<=zoom_start-.025]
    zoom=[s for s in samples if zoom_start+.025<=s['castElapsed']<=settle-.025]
    assert hold and pan and zoom,(folder,'missing transition samples')
    held_fov=float(np.median([s['effectiveFov'] for s in hold]))
    assert max(abs(s['effectiveFov']-held_fov) for s in pan)<.3,(folder,'lens moved during pan')
    assert all(s['effectiveFov']<=held_fov+.3 for s in pan+zoom+settled),(folder,'target transition zoomed out')
    assert np.median([s['effectiveFov'] for s in settled])<held_fov-.10,(folder,'target shot did not zoom in')
    for axis in ('pitch','yaw'):
        assert max(s['effectiveRotation'][axis] for s in zoom)-min(s['effectiveRotation'][axis] for s in zoom)<.3,(folder,'pan continued during zoom')
        held_angle=float(np.median([s['effectiveRotation'][axis] for s in hold]))
        assert all(abs(s['effectiveRotation'][axis]-held_angle)<.3 for s in pan+zoom+settled),(folder,'target handoff changed camera angle',axis)
    assert max(np.linalg.norm(vec(s['effectiveLocation'])-vec(zoom[-1]['effectiveLocation'])) for s in zoom)<1,(folder,'camera kept moving during zoom')
    pan_start_position=vec(hold[-1]['effectiveLocation'])
    pan_end_position=vec(settled[0]['effectiveLocation'])
    assert np.linalg.norm(pan_end_position-pan_start_position)>20,(folder,'target pan did not move the camera')
    p,y=map(math.radians,(hold[-1]['effectiveRotation']['pitch'],hold[-1]['effectiveRotation']['yaw']))
    held_forward=np.array([math.cos(p)*math.cos(y),math.cos(p)*math.sin(y),math.sin(p)])
    assert abs((pan_end_position-pan_start_position)@held_forward)<2,(folder,'target pan changed camera depth')
    action_name=next(e['set']['Unit_PlayAnimByName_AnimationName'] for e in events if e['set'].get('Unit_PlayAnimByName_AnimationName') in ('LB1','attack_A','magic_attack')).lower()
    assert not any(s.get('casterAnimation','').lower()==action_name for s in hold+pan+zoom),(folder,'attack animation began before the handoff finished')
    assert abs(samples[-1]['effectiveRotation']['yaw'])<.1,(folder,'camera did not restore')
    active=set(next(e for e in records if e['kind']=='native_command_list')['skills'].values())
    expected=set(map(int,unit['skills']))
    assert expected<=active and not(set(map(int,unit.get('step1AutomaticActions',{})))&active),(folder,'active kit mismatch')
    before=next(e for e in records if e['kind']=='owner_mp_before')
    after=next(e for e in records if e['kind']=='owner_mp_after')
    assert before['available'] and after['available'] and before['cost']==1
    assert int(before['mp'])-int(after['mp'])==1,(folder,'command did not cost exactly 1 MP',before,after)
    results.append({'vision':unit['en'],'skill':skill,'run':folder.name,'selectedTargets':target_count,
                    'targetBodyBounds':dict(zip(('left','top','right','bottom'),[round(n,4) for n in box])),
                    'restored':True,'activeKitVerified':True,'mpSpent':1,'savesUnchanged':True,
                    'panHeldLens':True,'panPreservedDepth':True,'zoomHeldDirection':True,'zoomHeldPosition':True,'castFov':round(held_fov,3),
                    'targetFov':round(float(np.median([s['effectiveFov'] for s in settled])),3)})
(WORK/'runtime-verification.json').parent.mkdir(parents=True,exist_ok=True)
partial='--partial' in sys.argv
if not partial:
    assert {13500,13501,13502,13503}<={next(u['id'] for u in units if u['en']==r['vision']) for r in results},'Native verification is missing a vision'
assert results,'No completed native checks for the installed package'
(WORK/('runtime-verification.partial.json' if partial else 'runtime-verification.json')).write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,indent=2))
