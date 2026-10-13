"""Verify actual native denial, unchanged MP/target state and continuation."""
from verify_combat_observation import diagnostic_skill_id
from collections import Counter
import argparse,json,re
from verify_combat_observation import OUT,read_json,sha,verify_artifacts


def verify(directory,build):
    skill_id = diagnostic_skill_id(directory)
    run=verify_artifacts(directory,build,denial=True)
    assert run['convertedAbilityRequested'] and not run.get('convertedExpiryRequested')
    assert run.get('fixtureCompleted') and run.get('fixtureTerminated') and not run.get('fixtureFailed')
    fixture=read_json(directory/'converted-ability-build.json')
    profile=read_json(directory/'converted-profile.json')
    assert fixture['status']=='built' and fixture['scope']=='temporary_converted_fire_fixture'
    assert fixture['source']=='JP_2024/magic/20010' and fixture['skillId']==skill_id
    assert fixture['profileSha256']==sha(directory/'converted-profile.json')
    assert profile['supported'] and fixture['experiment']['weaknessPhase']=='after'
    assert len(run['temporaryContentPackages'])==3
    assert sorted(v.lower() for v in run['temporaryContentPackages'].values())==sorted(fixture['files'].values())
    log_path=directory/'collected-ue4ss/UE4SS.log';log=log_path.read_text(encoding='utf8',errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=','turn_owner_failed=','[FFRConvertedDriver] read_failed='))
    assert log.count('fire_row_verified')==1
    assert log.count('denial_fire_requested ')==log.count('denial_fire_returned')==1
    assert log.count('denial_defend_requested ')==log.count('denial_defend_returned')==1
    assert log.count('converted_observation_complete')==1
    events=[]
    for number,line in enumerate(log.splitlines(),1):
        match=re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$',line)
        if match:events.append({**json.loads(match[2]),'logLine':number})
    counts=Counter(e['event'] for e in events)
    assert counts['registered']==13 and counts['native_attached']==1
    assert counts['fixture_enforcement_attached']==counts['fixture_native_denial']==1
    assert not any(counts[k] for k in ('native_attach_failed','registration_failed','read_failed','trace_capacity','query_capacity','native_observation_capacity'))
    attach=next(e for e in events if e['event']=='fixture_enforcement_attached')
    assert attach['allowed'] is True and attach['mode']=='enforce' and attach['skillId']==skill_id
    handshake=next(e for e in events if e['event']=='native_attached')
    assert handshake['mode']=='enforce_fixture' and handshake['reason']=='attached'
    guards=[e for e in events if e['event']=='native_guard'];assert len(guards)==1
    guard=guards[0];denied=next(e for e in events if e['event']=='fixture_native_denial')
    assert guard['nativeAllowed'] is True and denied['nativeAllowed'] is True and denied['decision'] is False
    assert guard['skillId']==denied['skillId']==skill_id
    assert guard['job']==guard['rootJob']==denied['job'] and guard['actor']==denied['actor']>0
    assert guard['actionCount']==guard['targetCount']==1
    commands=[e for e in events if e['event']=='command_decide']
    assert len(commands)==2
    assert [e['actions'] for e in commands]==[
        [{'item':False,'skillId':skill_id,'targets':[1],'uniqueId':0}],
        [{'item':False,'skillId':400010,'targets':[0],'uniqueId':0}]]
    assert commands[0]['logLine']<guard['logLine']<denied['logLine']<commands[1]['logLine']
    starts=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra')]
    assert not any(e['skillId']==skill_id for e in starts)
    stock=[e for e in starts if e['skillId']==400010]
    assert stock and all(e['logLine']>commands[1]['logLine'] and e['uniqueId']==0 and e['targets']==[0]
        and e['owner']['actorAddress']==guard['actor'] for e in stock)
    request=re.findall(r'denial_fire_requested owner=(\d+) target=(\d+) turn=(\d+) caster_mp=(\d+) enemy_hp=(\d+) enemy_fire=(\d+)',log)
    assert len(request)==1
    owner,target,initial,mp,hp,resistance=map(int,request[0])
    assert (owner,target,mp,hp,resistance)==(0,1,43,200,0)
    samples=[tuple(map(int,v)) for v in re.findall(r'denial_sample phase=(\d+) turn=(\d+) caster_hp=(\d+) caster_mp=(\d+) enemy_hp=(\d+) enemy_fire=(\d+)',log)]
    after=[v for v in samples if v[0]>0];assert after
    assert all(v[2]>0 and (v[3],v[4],v[5])==(mp,hp,resistance) for v in after)
    complete=re.findall(r'denial_complete initial_turn=(\d+) final_turn=(\d+) caster_mp=(\d+) enemy_hp=(\d+) enemy_fire=(\d+)',log)
    assert len(complete)==1
    first,last,final_mp,final_hp,final_resistance=map(int,complete[0])
    assert first==initial and last==first+2 and (final_mp,final_hp,final_resistance)==(mp,hp,resistance)
    return {'run':directory.name,'status':'passed','runSha256':sha(directory/'run.json'),'logSha256':sha(log_path),
        'fixtureProfileSha256':fixture['profileSha256'],'nativeGuard':guard,'nativeDenial':denied,
        'source':'JP_2024/magic/20010','nativeBridgeDllSha256':build['dllSha256'],
        'managedCommands':[skill_id],'deniedCastMPSpent':0,'deniedCastDamage':0,'weaknessAdded':False,
        'deniedSkillStartNotifications':0,'stockDefendStartNotifications':len(stock),
        'initialOwnerCounter':first,'finalOwnerCounter':last,'originalSaveFilesUnchanged':True,
        'existingGamePackagesUnchanged':True,'temporaryInstallationRemoved':True,
        'scope':'Forced-denial native boundary fixture only; no availability lifecycle/loadout resolver or holds released.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');args=parser.parse_args()
    result=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'))
    (OUT/'native-denial-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2))
