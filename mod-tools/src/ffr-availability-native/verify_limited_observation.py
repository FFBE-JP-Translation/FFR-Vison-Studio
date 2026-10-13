"""Verify canonical one-use authorization against actual native Fire execution."""
from verify_combat_observation import diagnostic_skill_id
from collections import Counter
import argparse,json,re
from verify_combat_observation import OUT,read_json,sha,verify_artifacts


def verify(directory,build,*,menu=False):
    skill_id = diagnostic_skill_id(directory)
    run=verify_artifacts(directory,build,limited=True,menu=menu)
    attempts=1 if menu else 2
    assert run['convertedAbilityRequested'] and not run.get('convertedExpiryRequested')
    assert run.get('fixtureCompleted') and run.get('fixtureTerminated') and not run.get('fixtureFailed')
    fixture=read_json(directory/'converted-ability-build.json');profile=read_json(directory/'converted-profile.json')
    assert fixture['status']=='built' and fixture['scope']=='temporary_converted_fire_fixture'
    assert fixture['source']=='JP_2024/magic/20010' and fixture['skillId']==skill_id
    assert fixture['profileSha256']==sha(directory/'converted-profile.json') and profile['supported']
    assert fixture['experiment']['weaknessPhase']=='after'
    assert len(run['temporaryContentPackages'])==3
    assert sorted(v.lower() for v in run['temporaryContentPackages'].values())==sorted(fixture['files'].values())
    log_path=directory/'collected-ue4ss/UE4SS.log';log=log_path.read_text(encoding='utf8',errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=','turn_owner_failed=','limited_binding_failed'))
    assert log.count('fire_row_verified')==1
    assert log.count('limited_fire_requested ')==log.count('limited_fire_returned ')==attempts
    assert log.count('limited_defend_requested ')==log.count('limited_defend_returned')==1
    assert log.count('converted_observation_complete')==1
    events=[]
    for number,line in enumerate(log.splitlines(),1):
        match=re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$',line)
        if match:events.append({**json.loads(match[2]),'logLine':number})
    counts=Counter(e['event'] for e in events)
    assert counts['registered']==13 and counts['native_attached']==counts['limited_enforcement_attached']==1
    assert counts['limited_battle']==1 and counts['limited_selection']==counts['limited_authorization']==attempts
    assert not any(counts[k] for k in ('native_attach_failed','registration_failed','read_failed','trace_capacity','query_capacity','native_observation_capacity'))
    attached=next(e for e in events if e['event']=='limited_enforcement_attached')
    assert attached['allowed'] is True and attached['mode']=='enforce' and attached['skillId']==skill_id
    assert next(e for e in events if e['event']=='native_attached')['mode']=='enforce_fixture'
    begin=next(e for e in events if e['event']=='limited_battle')
    assert begin['before'] is False and begin['after'] is True and begin['subsystem']>0
    assert begin['callerRva']==0x4fc7e0f and begin['battle']=='fixture-battle:1'
    authorization=[e for e in events if e['event']=='limited_authorization']
    assert [(e['nativeAllowed'],e['decision'],e['reason'],e['usedBefore'],e['usedAfter']) for e in authorization]==[
        (True,True,'committed',0,1),(True,False,'uses_exhausted',1,1)][:attempts]
    assert [e['cast'] for e in authorization]==['fixture-cast:1','fixture-cast:2'][:attempts]
    guards=[e for e in events if e['event']=='native_guard'];assert len(guards)==attempts
    assert all(e['nativeAllowed'] is True and e['skillId']==skill_id and e['job']==e['rootJob']
        and e['actionCount']==e['targetCount']==1 for e in guards)
    assert all(e['job']==g['job'] and e['actor']==g['actor'] for e,g in zip(authorization,guards))
    assert guards[0]['actor']>0 and len({e['actor'] for e in guards})==1
    commands=[e for e in events if e['event']=='command_decide'];assert len(commands)==attempts+1
    assert [e['actions'] for e in commands]==[
        [{'item':False,'skillId':skill_id,'targets':[1],'uniqueId':0}]]*attempts+[
        [{'item':False,'skillId':400010,'targets':[0],'uniqueId':0}]]
    selections=[e for e in events if e['event']=='limited_selection']
    assert [e['cast'] for e in selections]==[e['cast'] for e in authorization]
    assert [e['turn'] for e in selections]==[1,2][:attempts]
    assert len({e['payload'] for e in selections})==attempts
    for c,s,g,a in zip(commands,selections,guards,authorization):
        # Different pre-hook registrations may log selection/command in either
        # order; both must precede the direct native execution callback.
        assert max(c['logLine'],s['logLine'])<g['logLine']<a['logLine']
    starts=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra')]
    fire=[e for e in starts if e['skillId']==skill_id];stock=[e for e in starts if e['skillId']==400010]
    assert len(fire)==4 and len({e['payload'] for e in fire})==1
    assert all(authorization[0]['logLine']<e['logLine']<commands[1]['logLine'] for e in fire)
    assert len(stock)==4 and all(e['logLine']>commands[-1]['logLine'] for e in stock)
    assert all(e['owner']['actorAddress']==guards[0]['actor'] and e['uniqueId']==0 for e in fire+stock)
    requests=[tuple(map(int,v)) for v in re.findall(r'limited_fire_requested ordinal=(\d+) owner=(\d+) target=(\d+) turn=(\d+) caster_mp=(\d+) enemy_hp=(\d+)',log)]
    assert len(requests)==attempts and requests[0]==(1,0,1,1,43,200)
    result=re.findall(r'limited_first_result caster_mp=(\d+) enemy_hp=(\d+) enemy_fire=(\d+)',log)
    assert len(result)==1
    accepted_mp,accepted_hp,accepted_resistance=map(int,result[0])
    assert accepted_mp==39 and 0<accepted_hp<200 and accepted_resistance==1
    if not menu: assert requests[1]==(2,0,1,2,39,accepted_hp)
    samples=[tuple(map(int,v)) for v in re.findall(r'limited_sample phase=(\d+) turn=(\d+) caster_hp=(\d+) caster_mp=(\d+) enemy_hp=(\d+) enemy_fire=(\d+)',log)]
    after=[v for v in samples if v[0]>=2];assert after
    assert all(v[2]>0 and v[3]==39 and v[4]==accepted_hp for v in after)
    complete=re.findall(r'limited_complete initial_turn=(\d+) final_turn=(\d+) caster_mp=(\d+) enemy_hp=(\d+) enemy_fire=(\d+)',log)
    assert len(complete)==1
    first,last,mp,hp,resistance=map(int,complete[0])
    assert (first,last,mp,hp)==(1,attempts+2,39,accepted_hp)
    turns=[e for e in events if e['event']=='limited_turn']
    assert [e['ordinal'] for e in turns]==list(range(1,attempts+3))
    assert begin['logLine']<turns[0]['logLine']
    assert {e['battle'] for e in turns}=={begin['battle']}
    assert {e['actor'] for e in turns}=={guards[0]['actor']} and len({e['owner'] for e in turns})==1
    queries=[e for e in events if e['event']=='limited_menu_query']
    if menu:
        assert counts['limited_menu_attached']==1 and not counts['limited_menu_capacity']
        assert next(e for e in events if e['event']=='limited_menu_attached')['allowed'] is True
        assert queries and all(e['skillId']==skill_id for e in queries)
        assert all(not e['decision'] for e in queries if not e['nativeAllowed'])
        direct=[e for e in queries if e['callerRva']==0x515e0b9 and e['uniqueId']==0]
        assert any(e['nativeAllowed'] and e['decision'] and e['reason']=='available' and e['used']==0
            and e['turn']==1 and e['logLine']<authorization[0]['logLine'] for e in direct)
        denied=[e for e in direct if e['nativeAllowed'] and not e['decision'] and e['reason']=='uses_exhausted'
            and e['turn']==2 and e['used']==1 and authorization[0]['logLine']<e['logLine']<commands[-1]['logLine']]
        assert denied,'No exhausted menu query before the stock command'
        blocked=re.findall(r'limited_menu_blocked owner=(\d+) turn=(\d+) caster_mp=(\d+) enemy_hp=(\d+)',log)
        assert blocked==[('0','2','39',str(accepted_hp))]
        assert re.findall(r'limited_defend_requested owner=(\d+) turn=(\d+) target=(\d+)',log)==[('0','2','0')]
    else:
        assert not queries and not counts['limited_menu_attached']
    return {'status':'passed','run':directory.name,'runSha256':sha(directory/'run.json'),'logSha256':sha(log_path),
        'source':'JP_2024/magic/20010','fixtureRule':'synthetic maximumUses=1',
        'nativeBridgeDllSha256':build['dllSha256'],'authorizations':authorization,
        'canonicalRuntimeSha256':sha(directory/'Mods/FFRAvailabilityRuntime/Scripts/availability.lua'),
        'canonicalHostSha256':sha(directory/'Mods/FFRAvailabilityRuntime/Scripts/native_host.lua'),
        'nativeBattleBegin':begin,'ownerTurns':turns,'acceptedCasts':1,'deniedCasts':attempts-1,'totalMPSpent':4,'totalDamage':200-hp,
        'menuQueries':queries,'menuBlocksExhaustedCommand':menu,'stockDefendUsesSameOpportunity':menu,
        'acceptedSkillStartNotifications':len(fire),'deniedSkillStartNotifications':0,
        'stockDefendStartNotifications':len(stock),'originalSaveFilesUnchanged':True,
        'existingGamePackagesUnchanged':True,'temporaryInstallationRemoved':True,
        'scope':'Canonical one-use engine and native bridge with a fixture-only ordinary actor/selection resolver. No production lifecycle/loadout binding or source holds released.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');parser.add_argument('--menu',action='store_true');args=parser.parse_args()
    result=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'),menu=args.menu)
    output='native-limited-menu-validation.json' if args.menu else 'native-limited-validation.json'
    (OUT/output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2))
