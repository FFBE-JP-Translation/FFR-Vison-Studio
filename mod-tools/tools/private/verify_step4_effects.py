"""Cooked readback plus independent source-clock and presentation-policy checks."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import verify_step3_effects as previous
from prepare_step3_effects import read,write
import ffbe_presentation as p

ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/effects-step4'

def check(job):
    sid=job['skill'];plan=job['plan'];action=p.action_start(plan)
    old=next(j['plan'] for j in read(ROOT/'checkpoints/ffbe-effects-step3/records/plans.json') if j['skill']==sid)
    old_action=p.action_start(old)
    assert old_action-action==19200,(sid,'expected 0.8 seconds less host staging')
    def relative(plan,kind):
        origin=p.action_start(plan)
        return [{**e,'time':e['time']-origin} for e in plan['events'] if e['set']['EventType']==kind]
    for kind in ('OtherReaction','SsActorSpawnSpriteStudioActor','SsActorPlayAnimToSsID','SsActorDestroyToSsID'):
        # Casting layers move with the cast; action layers move with action.
        if kind=='OtherReaction': assert relative(old,kind)==relative(plan,kind),(sid,'source hit clock')
    old_sounds=[e for e in old['events'] if e['set']['EventType']=='SoundPlayHitSound']
    sounds=[e for e in plan['events'] if e['set']['EventType']=='SoundPlayHitSound']
    assert [{**e,'time':e['time']-old_action} for e in old_sounds[1:]]==[{**e,'time':e['time']-action} for e in sounds[1:]]
    assert old_sounds[0]['set']==sounds[0]['set'] and old_sounds[0]['time']-sounds[0]['time']==9600
    cameras=[e for e in plan['events'] if e['set']['EventType']=='NativeParticipantCamera']
    assert action==cameras[-1]['time']+6*800
    assert cameras[-1]['time']==cameras[-2]['time']+6*800
    moving=any(e['set']['EventType']=='NativeGroundApproach' for e in plan['events'])
    assert cameras[-1]['set']['NativeParticipantCamera_Shot']==('targets_zoom' if moving else 'participants_zoom')
    old_cameras=[e for e in old['events'] if e['set'].get('NativeParticipantCamera_Shot')=='caster']
    assert [{**e,'time':e['time']-9600} for e in old_cameras]==cameras[:-2]
    if job.get('effectTrial'):
        for event in plan['events']:
            s=event['set']
            if s['EventType']=='NativeActorRootSnapshot':
                assert s['NativeActorRootSnapshot_SortLayer'] in (-1,-2)
            if s['EventType']=='NativeScreenPlane': assert s['NativeScreenPlane_VisionUnitId']==job['vision']
    if sid==485130:
        risen=[e for e in plan['events'] if 'NativeScreenPlane_ViewportRise' in e['set']]
        assert risen and all(e['set']['NativeScreenPlane_ViewportRise']==.12 for e in risen)
        assert {e['set']['NativeScreenPlane_Id'] for e in risen}=={'FFBE_485130_0'}
    result=previous.verify(job,compare_checkpoint=False)
    result.pop('matchesAcceptedCheckpointCameraAndHits')
    result.update(sourceRelativeHitsAndSoundsPreserved=True,stagingSecondsRemoved=.8,stationaryCasterIncluded=not moving)
    return result

def main():
    previous.WORK=WORK
    jobs=read(WORK/'plans.json');assert len(jobs)==14
    with ThreadPoolExecutor(max_workers=3) as pool: results=list(pool.map(check,jobs))
    write(WORK/'cooked-verification.json',results)
    print('All fourteen cooked timelines match; source hit/sound clocks preserved and new staging verified.')

if __name__=='__main__':main()
