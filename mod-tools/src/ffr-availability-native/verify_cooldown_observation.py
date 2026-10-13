"""Verify an actual FFBE cooldown through waiting, native reuse and re-locking."""
from verify_combat_observation import diagnostic_skill_id
import argparse
from collections import Counter
import json
import re
from verify_source_observation import verify_source_artifacts
from verify_combat_observation import OUT,read_json,sha

SOURCE='JP_2022/ability/1007200'


def verify(directory,build):
    skill_id = diagnostic_skill_id(directory)
    run,fixture,profile,plan,gate,runtime=verify_source_artifacts(directory,build,SOURCE,'cooldown')
    assert gate['kind']=='cooldown' and gate['cooldownTurns']==5 and gate['availableOnTurn']==1
    assert gate['singleCastWhenDualWielding'] is False and gate['childId']=='1007201'
    assert gate['raw']==[0,3,130,[1007201,1,[4,4],1]]
    assert profile['timeline']['hitFrames']==[60]
    effects=profile['conversion']['native']['effects']
    assert [e['set']['EffectType'] for e in effects]==['ParameterVariation']*2
    assert [e['set']['ParamList'] for e in effects]==[
        [2000,1,0,-1,0,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1],
        [500,2,0,-1,0,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1]]
    log_path=directory/'collected-ue4ss/UE4SS.log';log=log_path.read_text(encoding='utf8',errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=','turn_owner_failed=','limited_binding_failed'))
    assert log.count('cooldown_row_verified source='+SOURCE)==1
    assert log.count('cooldown_cast_requested ')==log.count('cooldown_cast_returned ')==log.count('cooldown_result ')==2
    assert log.count('cooldown_menu_blocked ')==log.count('cooldown_defend_requested ')==log.count('cooldown_defend_returned ')==5
    assert log.count('cooldown_complete ')==log.count('converted_observation_complete')==1
    events=[]
    for number,line in enumerate(log.splitlines(),1):
        match=re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$',line)
        if match:events.append({**json.loads(match[2]),'logLine':number})
    counts=Counter(e['event'] for e in events)
    assert counts['registered']==13
    for name in ('native_attached','limited_enforcement_attached','limited_battle','limited_menu_attached'):
        assert counts[name]==1,name
    for name in ('limited_selection','limited_authorization','native_guard'):assert counts[name]==2,name
    assert not any(counts[k] for k in ('native_attach_failed','registration_failed','read_failed','trace_capacity','query_capacity','native_observation_capacity','limited_menu_capacity'))
    def one(name):return next(e for e in events if e['event']==name)
    def all_events(name):return [e for e in events if e['event']==name]
    attached=one('limited_enforcement_attached')
    assert attached['allowed'] and attached['command']==SOURCE and attached['gate']==gate['key'] and attached['mode']=='enforce'
    assert one('native_attached')['mode']=='enforce_fixture' and one('limited_menu_attached')['allowed']
    begin=one('limited_battle')
    assert begin['before'] is False and begin['after'] is True and begin['callerRva']==0x4fc7e0f
    turns=all_events('limited_turn');authorizations=all_events('limited_authorization')
    guards=all_events('native_guard');selections=all_events('limited_selection')
    assert [e['ordinal'] for e in turns]==list(range(1,9))
    assert begin['logLine']<turns[0]['logLine'] and len({e['owner'] for e in turns})==1
    assert len({e['actor'] for e in guards+turns+selections+authorizations})==1 and guards[0]['actor']>0
    assert [e['turn'] for e in authorizations]==[1,6]
    assert [(e['readyBefore'],e['readyAfter']) for e in authorizations]==[(1,6),(6,11)]
    assert all(e['nativeAllowed'] is True and e['decision'] is True and e['reason']=='committed'
        and e['usedBefore']==e['usedAfter']==0 for e in authorizations)
    assert [e['cast'] for e in authorizations]==[e['cast'] for e in selections]==['fixture-cast:1','fixture-cast:2']
    assert [e['turn'] for e in selections]==[1,6] and all(e['target']==0 for e in selections)
    assert all(e['nativeAllowed'] is True and e['skillId']==skill_id and e['job']==e['rootJob']
        and e['targetCount']==e['actionCount']==1 for e in guards)
    assert [e['job'] for e in guards]==[e['job'] for e in authorizations]
    commands=all_events('command_decide')
    assert [e['actions'] for e in commands]==[
        [{'item':False,'skillId':skill,'targets':[0],'uniqueId':0}]
        for skill in [skill_id,400010,400010,400010,400010,skill_id,400010]]
    source_commands=[commands[0],commands[5]]
    for command,selection,guard,authorization in zip(source_commands,selections,guards,authorizations):
        assert max(command['logLine'],selection['logLine'])<guard['logLine']<authorization['logLine']
    starts=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra')]
    source_starts=[e for e in starts if e['skillId']==skill_id]
    defend_starts=[e for e in starts if e['skillId']==400010]
    assert len(source_starts)==8 and len(defend_starts)==20
    assert len({e['payload'] for e in source_starts})==2 and len({e['payload'] for e in defend_starts})==5
    for first,end in ((authorizations[0]['logLine'],commands[1]['logLine']),(authorizations[1]['logLine'],commands[6]['logLine'])):
        assert len([e for e in source_starts if first<e['logLine']<end])==4
    assert all(e['uniqueId']==0 and e['targets']==[0] and e['owner']['actorAddress']==guards[0]['actor'] for e in source_starts+defend_starts)
    queries=all_events('limited_menu_query')
    direct=[e for e in queries if e['callerRva']==0x515e0b9 and e['uniqueId']==0]
    assert all(not e['decision'] for e in queries if not e['nativeAllowed'])
    for turn,ready in ((1,1),(6,6)):
        assert any(e['turn']==turn and e['readyTurn']==ready and e['nativeAllowed'] and e['decision']
            and e['reason']=='available' for e in direct)
    blocked=[2,3,4,5,7]
    for turn in blocked:
        assert any(e['turn']==turn and e['readyTurn']==(6 if turn<6 else 11) and e['nativeAllowed']
            and not e['decision'] and e['reason']=='cooldown' for e in direct)
        assert not any(e['turn']==turn and e['decision'] for e in queries)
    blocked_log=[tuple(map(int,s)) for s in re.findall(r'cooldown_menu_blocked turn=(\d+) after_cast=(\d+)',log)]
    assert blocked_log==[(2,1),(3,1),(4,1),(5,1),(7,2)]
    defends=[tuple(map(int,s)) for s in re.findall(r'cooldown_defend_requested owner=(\d+) target=(\d+) turn=(\d+)',log)]
    assert defends==[(0,0,t) for t in blocked]
    casts=[tuple(map(int,s)) for s in re.findall(r'cooldown_cast_requested ordinal=(\d+) owner=(\d+) target=(\d+) turn=(\d+) caster_hp=(\d+) caster_mp=(\d+)',log)]
    assert len(casts)==2 and [c[:4] for c in casts]==[(1,0,0,1),(2,0,0,6)] and all(c[5]==43 for c in casts)
    heals=[tuple(map(int,s)) for s in re.findall(r'cooldown_result ordinal=(\d+) turn=(\d+) before_hp=(\d+) after_hp=(\d+) caster_mp=(\d+)',log)]
    assert len(heals)==2 and [h[:2] for h in heals]==[(1,1),(2,6)]
    assert all(0<h[2]<h[3]==382 and h[2]==c[4] and h[4]==43 for h,c in zip(heals,casts))
    samples=[tuple(map(int,s)) for s in re.findall(r'cooldown_sample phase=(\d+) turn=(\d+) caster_hp=(\d+) max_hp=(\d+) caster_mp=(\d+) enemy_hp=(\d+)',log)]
    assert samples and all(0<s[2]<=s[3]==382 and s[4]==43 and s[5]==200 for s in samples)
    assert re.findall(r'cooldown_complete casts=(\d+) first_turn=(\d+) second_turn=(\d+) final_turn=(\d+) caster_mp=(\d+) enemy_hp=(\d+)',log)==[('2','1','6','8','43','200')]
    return {'status':'passed','scope':'real_ffbe_cooldown_payload_with_native_reuse','run':directory.name,
        'runSha256':sha(directory/'run.json'),'logSha256':sha(log_path),'source':SOURCE,'child':'JP_2022/ability/1007201',
        'sourceRule':gate,'sourceSnapshotRetained':True,'originalExportHoldRetained':True,
        'sourcePlanSha256':sha(directory/'availability-plan.json'),'sourceContractSha256':sha(runtime/'source_contract.lua'),
        'nativeBridgeDllSha256':build['dllSha256'],'fixtureDllSha256':read_json(directory/'fixture-build.json')['dllSha256'],
        'canonicalRuntimeSha256':sha(runtime/'availability.lua'),'canonicalHostSha256':sha(runtime/'native_host.lua'),
        'nativeBattleBegin':begin,'authorizations':authorizations,'ownerTurns':turns,'menuQueries':queries,
        'acceptedCasts':2,'acceptedOwnerTurns':[1,6],'unavailableOwnerTurns':blocked,'readyTurnsAfterCasts':[6,11],
        'heals':[{'ownerTurn':h[1],'before':h[2],'after':h[3]} for h in heals],
        'mpSpent':0,'enemyDamage':0,'stockDefendCommands':5,'sourceSkillStartNotifications':8,
        'originalSaveFilesUnchanged':True,'existingGamePackagesUnchanged':True,'temporaryInstallationRemoved':True,
        'productionAvailabilityPayloadsReleased':0,
        'limitations':['One ordinary actor and self-target payload; general lifecycle/loadout remains unbound.',
            'Source HP/MP magnitudes use existing converter scaling and native maximum caps.',
            'MP started full, so this run verifies no extra MP cost; it does not measure the MP refill amount.',
            'Source allows dual-wield casts; that flag is retained but dual wield is not exercised.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'))
    (OUT/'native-source-cooldown-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))
