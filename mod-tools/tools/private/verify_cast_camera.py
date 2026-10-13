"""Independently read every cooked camera-kit command and check its timeline."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
import ffrenv
import ffbe_resonance as sequence
from ability_converter import commands

WORK = Path(os.environ.get('FFR_CAMERA_WORK') or ROOT/'build/cast-camera-step1')
ASSETS = ROOT/'build/visions_mod/assets'

def verify_one(job):
    unit, sid, recipe, lb = job
    seq_id = sid+1 if lb else 2_000_000+sid*2
    folder = WORK/'cooked'/str(sid); folder.mkdir(parents=True, exist_ok=True)
    mapping = folder/'Mappings.usmap'; shutil.copy2(ffrenv.USMAP, mapping)
    path = ASSETS/f'FFRS/Content/Sequencer/Battle/Skill/{sid}/{seq_id}/SEQ_Battle_{seq_id}_Master.uasset'
    def dump(verb):
        out = folder/(verb+'.json')
        result = subprocess.run([*ffrenv.FFRDT, verb, str(path), str(out), '--usmap', str(mapping)],
                                capture_output=True, text=True, encoding='utf-8')
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        return json.loads(out.read_text(encoding='utf-8-sig'))
    doc = dump('tojson'); functions = {int(k.split(':')[0]):v for k,v in dump('seqdump').items()}
    events = []
    for export in doc['Exports']:
        for prop in export.get('Data', []):
            if prop['Name'] != 'EventChannel': continue
            for time,value in zip(sequence.child(prop['Value'],'KeyTimes'), sequence.child(prop['Value'],'KeyValues')):
                while not isinstance(time, (int,float)): time = time[0] if isinstance(time,list) else time['Value']
                events.append((time,functions[sequence.child(value['Value'],'Ptrs','Function')]))
    events.sort(key=lambda e:e[0])
    bytype = lambda kind: [(t,e) for t,e in events if e['EventType']==kind]
    cameras = bytype('NativeParticipantCamera'); audio = bytype('SoundPlayHitSound')
    assert cameras and len(audio)==1, (sid,'shared cast sound/camera missing')
    assert cameras[0][0]==audio[0][0], (sid,'cast camera/audio clocks differ')
    target_step=unit.get('presentationStep')=='target_camera'
    caster_cameras=[(t,c) for t,c in cameras if c['NativeParticipantCamera_Shot']=='caster']
    assert all(c['NativeParticipantCamera_UnitId']==unit['id'] and c['NativeParticipantCamera_ZoomFactor']==1.15
               for _,c in caster_cameras), sid
    if target_step:
        assert len(cameras)==len(caster_cameras)+2 and [c['NativeParticipantCamera_Shot'] for _,c in cameras[-2:]]==['targets_pan','targets_zoom'],sid
        target_time,target=cameras[-1]
        assert (target['NativeParticipantCamera_CenterX'],target['NativeParticipantCamera_CenterY'],target['NativeParticipantCamera_HeightFraction'])==(.38,.58,.60),sid
        original=next(j['plan'] for j in json.loads((WORK/'step1-plans.json').read_text()) if j['skill']==sid)
        old_action=next(e['time'] for e in original['events'] if e['set'].get('Unit_PlayAnimByName_AnimationName') in ('LB1','attack_A','magic_attack'))
        cast_end=max(old_action,max(t+c['NativeParticipantCamera_Frame']*800 for t,c in caster_cameras))
        assert cameras[-2][0]==cast_end+7200,(sid,'0.3-second post-cast hold missing')
        assert target_time==cameras[-2][0]+cameras[-2][1]['NativeParticipantCamera_Frame']*800,(sid,'zoom does not follow pan')
        main=next(t for t,e in bytype('UnitPlayAnimByName') if e.get('Unit_PlayAnimByName_AnimationName') in ('LB1','attack_A','magic_attack'))
        assert main>=target_time+(target['NativeParticipantCamera_Frame']+2)*800,(sid,'animation precedes camera settle')
    else:
        assert len(cameras)==len(caster_cameras),sid
    moves = bytype('NativeGroundApproach')
    if moves:
        t, move = moves[0]; end=t+move['NativeGroundApproach_Frame']*800
        assert caster_cameras[0][0]<t and caster_cameras[-1][0]>=end, (sid,'follow misses travel endpoints')
        assert len(cameras)>=3 and move['NativeGroundApproach_Offset']['z']==0, sid
        if lb:
            assert next(t for t,e in bytype('UnitPlayAnimByName') if e.get('Unit_PlayAnimByName_AnimationName')=='LB1')>end, (sid,'attack starts before arrival')
    assert all(t2-t1>=e['NativeParticipantCamera_Frame']*800
               for (t1,e),(t2,_) in zip(cameras,cameras[1:])), (sid,'overlapping camera blends')
    reset=bytype('CameraSetDefault')[-1][0]
    assert reset>cameras[-1][0]+cameras[-1][1]['NativeParticipantCamera_Frame']*800, sid
    assert not bytype('NativeResonanceVisibility') and not bytype('SsActorSpawnSpriteStudioActor'), sid
    if recipe.get('cameraTest'):
        assert '[Camera Test]' in recipe['en'] and not bytype('OtherReaction'), (sid,'test command has gameplay effects')
    if not lb and recipe.get('mechanics')=='converted':
        main=next(t for t,e in bytype('UnitPlayAnimByName') if e.get('Unit_PlayAnimByName_AnimationName') in ('attack_A','magic_attack'))
        profile=commands.from_spec(recipe)
        assert [t for t,_ in bytype('OtherReaction')]==[main+f*400 for f in profile['timeline']['hitFrames']],sid
        assert bool(moves)==(profile['timeline']['moveType']==1), (sid,'movement changed')
    return {'vision':unit['en'],'name':recipe['en'],'skill':sid,'sequence':seq_id,'cameraEvents':len(cameras),
            'castTick':cameras[0][0],'castCue':audio[0][1]['Sound_PlayHitSound_playLabel'],
            'moves':bool(moves),'restoreTick':reset,'hits':len(bytype('OtherReaction'))}

if __name__=='__main__':
    units=json.loads((WORK/'units.json').read_text(encoding='utf-8'))
    jobs=[(u,int(sid),r,False) for u in units for sid,r in u['skills'].items()]
    jobs += [(u,440000+(u['id']-13099)*10,u['lb_custom'],True) for u in units]
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(verify_one,jobs))
    (WORK/'cooked-verification.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print(f'Verified {len(results)} cooked moves; {sum(r["moves"] for r in results)} moving commands; all cast cues, caster bindings, travel endpoints, source hits and restores passed.')
