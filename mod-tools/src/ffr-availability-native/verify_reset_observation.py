"""Verify real source uses reset across two native battles in one process."""
from verify_combat_observation import diagnostic_skill_id
import argparse
from collections import Counter
import json
import re
from verify_combat_observation import OUT,read_json,sha
from verify_source_observation import SOURCE,verify_source_artifacts
from verify_owned_observation import verify_grants
from verify_return_observation import trace


def verify(directory,build):
    skill_id = diagnostic_skill_id(directory)
    run,fixture,profile,plan,gate,runtime=verify_source_artifacts(directory,build,SOURCE,'limited',owned=True,reset=True)
    grants=verify_grants(directory,fixture)
    assert gate['raw']==[0,3,157,[516017,0,1,1,1,1,0,1,0]] and gate['maximumUses']==1
    assert profile['timeline']['hitFrames']==[10]
    effects=profile['conversion']['native']['effects']
    assert len(effects)==1 and effects[0]['set']['ParamList']==[20,4,2,-1,0,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1]
    log,events,lifecycle=trace(directory,reset=True);lines=log.splitlines()
    counts=Counter(e['event'] for e in events)
    assert counts['owned_enforcement_attached']==1
    assert counts['owned_battle']==counts['owned_end_before']==counts['owned_end_after']==2
    assert counts['owned_registered']==counts['owned_selection']==counts['owned_authorization']==4
    assert counts['owned_stale_query']==6 and counts['native_guard']==4
    assert log.count('owned_row_verified source='+SOURCE)==1
    assert log.count('owned_complete owners=2 source_casts=2 enemy_hp=200')==2
    assert 'converted_observation_complete' not in log
    driver=(directory/'Mods/FFRBattleProbe/Scripts/owned_driver.lua').read_text(encoding='utf8')
    assert ':SetUsableActiveSkill' not in driver and ':RefreshCommandSkill' not in driver
    def all_events(name):return [e for e in events if e['event']==name]
    begins=all_events('owned_battle');ends=all_events('owned_end_after');before=all_events('owned_end_before')
    assert [e['battle'] for e in begins]==[e['battle'] for e in ends]==['owned-battle:1','owned-battle:2']
    assert len({e['subsystem'] for e in begins+ends+before})==1
    assert begins[0]['logLine']<before[0]['logLine']<ends[0]['logLine']<begins[1]['logLine']<before[1]['logLine']<ends[1]['logLine']
    assert all(e['before'] is False and e['after'] is True and e['callerRva']==0x4fc7e0f for e in begins)
    assert all(e['during'] is True for e in before)
    assert all(e['during'] is False and e['active'] is False and e['ownersCleared']==2 for e in ends)
    registered=all_events('owned_registered')
    assert all(len({r[key] for r in registered})==4 for key in ('owner','actor','parameter'))
    assert len({e['cast'] for e in all_events('owned_selection')})==4
    assert len({e['payload'] for e in all_events('owned_selection')})==4
    results=[]
    for number,(begin,end,prior) in enumerate(zip(begins,ends,before),1):
        battle=begin['battle'];lo,hi=begin['logLine'],end['logLine']
        bounded=[e for e in events if lo<e['logLine']<hi]
        local_log='\n'.join(lines[lo-1:hi])
        owners=[r for r in registered if lo<r['logLine']<hi]
        assert {r['unitId'] for r in owners}=={1001,1002} and len(owners)==2
        assert all(r['owner'].startswith(battle+':owner:') and r['command']==SOURCE
            and skill_id in r['skills'] and 400010 in r['skills'] for r in owners)
        native_ends=[e for e in bounded if e['event']=='battle_end'];assert len(native_ends)==1
        assert end['payload']==prior['payload']==native_ends[0]['payload']
        commands=[e for e in bounded if e['event']=='command_decide']
        assert all(len(e['actions'])==1 and not e['notConsume'] and not e['actions'][0]['item'] for e in commands)
        assert Counter(e['actions'][0]['skillId'] for e in commands)=={skill_id:2,400010:2,400020:1}
        for r in owners:
            owner,actor,unique,unit=r['owner'],r['actor'],r['uniqueId'],r['unitId']
            auth=[e for e in bounded if e['event']=='owned_authorization' and e['owner']==owner]
            selection=[e for e in bounded if e['event']=='owned_selection' and e['owner']==owner]
            assert len(auth)==len(selection)==1;auth,selection=auth[0],selection[0]
            assert auth['nativeAllowed'] and auth['decision'] and auth['reason']=='committed'
            assert auth['usedBefore']==0 and auth['usedAfter']==1 and selection['turn']==1
            assert auth['cast']==selection['cast'] and auth['actor']==selection['actor']==actor
            assert auth['unitId']==selection['unitId']==unit and selection['uniqueId']==selection['target']==unique
            guards=[e for e in bounded if e['event']=='native_guard' and e['skillId']==skill_id and e['actor']==actor]
            assert len(guards)==1;guard=guards[0]
            assert guard['nativeAllowed'] and guard['job']==guard['rootJob']==auth['job']
            assert guard['actionCount']==guard['targetCount']==1
            assert selection['logLine']<guard['logLine']<auth['logLine']
            turns=[e for e in bounded if e['event']=='owned_turn' and e['owner']==owner]
            assert len(turns)>=2 and [e['ordinal'] for e in turns]==list(range(1,len(turns)+1))
            assert turns[0]['used']==0 and all(e['used']==1 for e in turns[1:])
            assert all(e['owned'] and e['actor']==actor and e['uniqueId']==unique and e['unitId']==unit for e in turns)
            queries=[e for e in bounded if e['event']=='owned_menu_query' and e['owner']==owner]
            assert any(e['nativeAllowed'] and e['decision'] and e['used']==0 and e['reason']=='available'
                and e['turn']==1 and e['logLine']<auth['logLine'] for e in queries)
            assert any(e['nativeAllowed'] and not e['decision'] and e['used']==1 and e['reason']=='uses_exhausted'
                and e['turn']>=2 and e['logLine']>auth['logLine'] for e in queries)
            own_commands=[c for c in commands if c['actions'][0]['uniqueId']==unique]
            for c in own_commands:
                a=c['actions'][0];assert a['targets']==[unique]
                next_line=min([e['logLine'] for e in commands if e['logLine']>c['logLine']]+[hi])
                starts=[e for e in bounded if e['event'] in ('skill_begin_message','skill_begin_libra')
                    and e['skillId']==a['skillId'] and e['owner']['actorAddress']==actor
                    and c['logLine']<e['logLine']<next_line]
                assert len(starts)==4 and len({e['payload'] for e in starts})==1
                assert all(e['uniqueId']==unique and e['targets']==[unique] for e in starts)
            resource=re.findall(fr'owned_result unit={unit} turn=(\d+) before_lb=(\d+) after_lb=(\d+) mp=(\d+)',local_log)
            assert len(resource)==1
            turn,lb_before,lb_after,mp=map(int,resource[0]);assert turn==1 and lb_after-lb_before==20
            samples=[tuple(map(int,v)) for v in re.findall(fr'owned_sample unit={unit} turn=(\d+) hp=(\d+) mp=(\d+) lb=(\d+)',local_log)]
            assert samples and all(hp>0 and sample_mp==mp for _,hp,sample_mp,_ in samples)
            loadouts=re.findall(fr'turn_owner_loadout unique={unique} actor={actor} unit={unit} active=([^\s]*) with_vision=([^\s]*)',local_log)
            assert loadouts and all(str(skill_id) in a.split(',') and str(skill_id) in b.split(',') for a,b in loadouts)
            stale=[e for e in all_events('owned_stale_query') if e['owner']==owner]
            assert Counter(e['phase'] for e in stale)==({'after_end':1,'after_begin':1} if number==1 else {'after_end':1})
            assert all(e['battle']==battle and e['used']==1 and not e['decision'] and e['reason']=='stale_battle' for e in stale)
            assert all(e['logLine']>end['logLine'] for e in stale)
            if number==1:assert next(e for e in stale if e['phase']=='after_begin')['currentBattle']==begins[1]['battle']
            results.append({'battle':battle,'owner':owner,'actor':actor,'unitId':unit,'uniqueId':unique,
                'gaugeBefore':lb_before,'gaugeAfter':lb_after,'mpSpent':0,'spentUses':1,'staleQueries':stale})
    return {'status':'passed','scope':'native_two_battles_reset_two_independent_source_uses','run':directory.name,
        'runSha256':sha(directory/'run.json'),**lifecycle,'source':SOURCE,'sourceRule':gate,
        'nativeGrants':grants,'owners':results,'acceptedCasts':4,'staleBattleQueriesRejected':6,
        'canonicalRuntimeSha256':sha(runtime/'availability.lua'),'canonicalHostSha256':sha(runtime/'native_host.lua'),
        'nativeBridgeDllSha256':build['dllSha256'],'fixtureDllSha256':read_json(directory/'fixture-build.json')['dllSha256'],
        'originalSaveFilesUnchanged':True,'existingGamePackagesUnchanged':True,'temporaryInstallationRemoved':True,
        'productionAvailabilityPayloadsReleased':0,
        'limitations':['Two native Escape/end/start cycles in a supplied debug field scaffold; ordinary field travel, wins and losses are not certified.',
            'Late grants, replacement during a battle and additional cast forms remain unbound.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'))
    (OUT/'native-reset-source-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))
