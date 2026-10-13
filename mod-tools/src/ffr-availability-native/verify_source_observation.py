"""Verify one real FFBE limited-use contract and payload in the native fixture."""
from verify_combat_observation import diagnostic_skill_id
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from verify_combat_observation import OUT,ROOT,read_json,sha,verify_artifacts

sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parent/'fixture'))
from ability_converter.catalog import SourceCatalog
from source_availability import source_profile

SOURCE='GL_2024/ability/150300'


def verify_source_artifacts(directory,build,source,case,*,owned=False,vision=False,life=False,cancel=False,reset=False,loadout=False):
    skill_id = diagnostic_skill_id(directory)
    run=verify_artifacts(directory,build,limited=True,menu=True,source=True,owned=owned,vision=vision,life=life,cancel=cancel,reset=reset,loadout=loadout)
    assert run.get('fixtureCompleted') and run.get('fixtureTerminated') and not run.get('fixtureFailed')
    assert not run.get('convertedExpiryRequested')
    fixture=read_json(directory/'converted-ability-build.json')
    assert fixture['status']=='built' and fixture['case']==case and fixture['skillId']==skill_id
    assert fixture['scope']==f'temporary_converted_{case}_fixture' and fixture['source']==source
    assert bool(fixture.get('nativeOwnedSource'))==owned
    assert bool(fixture.get('nativeVisionSource'))==vision
    assert bool(fixture.get('nativeLifeSource'))==life
    original=read_json(directory/'converted-profile.json')
    profile=read_json(directory/'experimental-profile.json')
    plan=read_json(directory/'availability-plan.json')
    runtime=directory/'Mods/FFRAvailabilityRuntime/Scripts'
    for path,key in ((directory/'converted-profile.json','profileSha256'),
            (directory/'experimental-profile.json','experimentalProfileSha256'),
            (directory/'availability-plan.json','availabilityPlanSha256'),
            (runtime/'source_contract.lua','sourceContractSha256')):
        assert sha(path)==fixture[key],path
    assert len(run['temporaryContentPackages'])==3
    assert sorted(v.lower() for v in run['temporaryContentPackages'].values())==sorted(fixture['files'].values())
    assert not original['supported'] and not plan['playable'] and not plan['payload']['validation']['tableCompatible']
    assert profile['supported'] and not profile['issues']
    assert fixture['experiment']['productionSupported'] is False
    assert fixture['experiment']['productionHold']==plan['bindingHold']
    assert len(plan['gates'])==1
    gate=plan['gates'][0]
    assert gate['owner']=='equipping_actor'
    assert fixture['experiment']['sourceRule']==gate
    # Rebuild from the authoritative original catalog, retaining the source
    # hold. The diagnostic helper also checks ordinary snapshot/table rejection.
    with SourceCatalog.open_existing(OUT/'v1/source-index.sqlite') as catalog, TemporaryDirectory(prefix='verify-source-',dir=OUT) as temp:
        expected_original,expected_profile,expected_plan=source_profile(catalog.get(source),catalog,Path(temp))
        assert expected_original==original and expected_plan==plan
        expected_profile['fixtureExperiment']=fixture['experiment']
        assert expected_profile==profile
        assert (Path(temp)/'source_contract.lua').read_bytes()==(runtime/'source_contract.lua').read_bytes()
    assert profile['set']['Cost']==0
    assert profile['set']['TargetType']=='Self' and profile['set']['DamageType']=='None'
    cooked_dir=Path(fixture['directory'])
    assert sha(cooked_dir/'cooked-skill-rows.json')==fixture['cookedRowsSha256']
    assert sha(cooked_dir/'cooked-effect-rows.json')==fixture['cookedEffectsSha256']
    row=read_json(cooked_dir/'cooked-skill-rows.json')['rows'][fixture['rowName']]
    for key,value in fixture['expectedRow'].items():
        if key not in ('Name','Description') and '.' not in key:assert row[key]==value,key
    return run,fixture,profile,plan,gate,runtime


def verify(directory,build):
    skill_id = diagnostic_skill_id(directory)
    run,fixture,profile,plan,gate,runtime=verify_source_artifacts(directory,build,SOURCE,'limited')
    assert gate['kind']=='limited' and gate['maximumUses']==1 and gate['childId']=='516017'
    assert gate['singleCastWhenDualWielding'] is True and gate['uniqueSelectionOnMulticast'] is False
    assert gate['raw']==[0,3,157,[516017,0,1,1,1,1,0,1,0]]
    assert profile['timeline']['hitFrames']==[10]
    effect=profile['conversion']['native']['effects']
    assert len(effect)==1 and effect[0]['set']['EffectType']=='ParameterVariation'
    assert effect[0]['set']['ParamList']==[20,4,2,-1,0,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1]
    assert profile['description']=='Restores 20% resonance gauge to the user.'
    log_path=directory/'collected-ue4ss/UE4SS.log'
    log=log_path.read_text(encoding='utf8',errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=','turn_owner_failed=','limited_binding_failed'))
    assert log.count('source_row_verified source='+SOURCE)==1
    for text in ('source_cast_requested ','source_cast_returned','source_first_result ',
                 'source_menu_blocked ','source_defend_requested ','source_defend_returned','source_complete ','converted_observation_complete'):
        assert log.count(text)==1,text
    events=[]
    for line_number,line in enumerate(log.splitlines(),1):
        match=re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$',line)
        if match:events.append({**json.loads(match[2]),'logLine':line_number})
    counts=Counter(e['event'] for e in events)
    assert counts['registered']==13
    for name in ('native_attached','limited_enforcement_attached','limited_battle','limited_selection','limited_authorization','native_guard','limited_menu_attached'):
        assert counts[name]==1,name
    assert not any(counts[k] for k in ('native_attach_failed','registration_failed','read_failed','trace_capacity','query_capacity','native_observation_capacity','limited_menu_capacity'))
    def one(name):return next(e for e in events if e['event']==name)
    attached=one('limited_enforcement_attached')
    assert attached['allowed'] and attached['command']==SOURCE and attached['gate']==gate['key'] and attached['mode']=='enforce'
    assert one('native_attached')['mode']=='enforce_fixture' and one('limited_menu_attached')['allowed']
    begin=one('limited_battle')
    assert begin['before'] is False and begin['after'] is True and begin['callerRva']==0x4fc7e0f
    guard=one('native_guard');authorization=one('limited_authorization');selection=one('limited_selection')
    assert guard['nativeAllowed'] is True and guard['skillId']==skill_id and guard['job']==guard['rootJob']
    assert guard['targetCount']==guard['actionCount']==1 and guard['actor']>0
    assert (authorization['nativeAllowed'],authorization['decision'],authorization['reason'],authorization['usedBefore'],authorization['usedAfter'])==(True,True,'committed',0,1)
    assert authorization['actor']==guard['actor']==selection['actor'] and authorization['job']==guard['job']
    assert authorization['cast']==selection['cast']=='fixture-cast:1' and selection['turn']==1 and selection['target']==0
    commands=[e for e in events if e['event']=='command_decide']
    assert [e['actions'] for e in commands]==[
        [{'item':False,'skillId':skill_id,'targets':[0],'uniqueId':0}],
        [{'item':False,'skillId':400010,'targets':[0],'uniqueId':0}]]
    assert max(commands[0]['logLine'],selection['logLine'])<guard['logLine']<authorization['logLine']
    starts=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra')]
    for skill,command in ((skill_id,commands[0]),(400010,commands[1])):
        observed=[e for e in starts if e['skillId']==skill]
        assert len(observed)==4 and len({e['payload'] for e in observed})==1
        assert all(e['uniqueId']==0 and e['targets']==[0] and e['owner']['actorAddress']==guard['actor'] for e in observed)
        assert all(e['logLine']>command['logLine'] for e in observed)
        if skill==skill_id:assert all(authorization['logLine']<e['logLine']<commands[1]['logLine'] for e in observed)
    turns=[e for e in events if e['event']=='limited_turn']
    assert [e['ordinal'] for e in turns]==[1,2,3]
    assert begin['logLine']<turns[0]['logLine'] and len({e['owner'] for e in turns})==1
    assert {e['actor'] for e in turns}=={guard['actor']}
    queries=[e for e in events if e['event']=='limited_menu_query']
    direct=[e for e in queries if e['callerRva']==0x515e0b9 and e['uniqueId']==0]
    assert all(not e['decision'] for e in queries if not e['nativeAllowed'])
    assert any(e['nativeAllowed'] and e['decision'] and e['reason']=='available' and e['used']==0
        and e['turn']==1 and e['logLine']<commands[0]['logLine'] for e in direct)
    assert any(e['nativeAllowed'] and not e['decision'] and e['reason']=='uses_exhausted' and e['used']==1
        and e['turn']==2 and commands[0]['logLine']<e['logLine']<commands[1]['logLine'] for e in direct)
    request=re.findall(r'source_cast_requested owner=(\d+) target=(\d+) turn=(\d+) caster_lb=(\d+) caster_mp=(\d+)',log)
    result=re.findall(r'source_first_result before_lb=(\d+) after_lb=(\d+) caster_mp=(\d+) enemy_hp=(\d+) turn=(\d+)',log)
    assert len(request)==len(result)==1
    owner,target,turn,old_lb,mp=map(int,request[0]);before_lb,after_lb,result_mp,enemy_hp,result_turn=map(int,result[0])
    assert (owner,target,turn,mp)==(0,0,1,43)
    assert before_lb==old_lb and after_lb-before_lb==20 and (result_mp,enemy_hp,result_turn)==(43,200,1)
    assert re.findall(r'source_defend_requested owner=(\d+) target=(\d+) turn=(\d+)',log)==[('0','0','2')]
    samples=[tuple(map(int,s)) for s in re.findall(r'source_sample phase=(\d+) turn=(\d+) caster_hp=(\d+) caster_mp=(\d+) caster_lb=(\d+) enemy_hp=(\d+)',log)]
    assert samples and all(s[2]>0 and s[3]==43 and s[5]==200 for s in samples)
    complete=re.findall(r'source_complete initial_turn=(\d+) final_turn=(\d+) caster_mp=(\d+) caster_lb=(\d+) enemy_hp=(\d+)',log)
    assert len(complete)==1 and tuple(map(int,complete[0]))[:3]==(1,3,43) and int(complete[0][4])==200
    return {'status':'passed','scope':'real_ffbe_limited_use_payload_in_ordinary_fixture','run':directory.name,
        'runSha256':sha(directory/'run.json'),'logSha256':sha(log_path),'source':SOURCE,'child':'GL_2024/ability/516017',
        'sourceRule':gate,'sourceSnapshotRetained':True,'originalExportHoldRetained':True,
        'sourcePlanSha256':sha(directory/'availability-plan.json'),'sourceContractSha256':sha(runtime/'source_contract.lua'),
        'nativeBridgeDllSha256':build['dllSha256'],'fixtureDllSha256':read_json(directory/'fixture-build.json')['dllSha256'],
        'canonicalRuntimeSha256':sha(runtime/'availability.lua'),'canonicalHostSha256':sha(runtime/'native_host.lua'),
        'nativeBattleBegin':begin,'nativeAuthorization':authorization,'ownerTurns':turns,'menuQueries':queries,
        'acceptedCasts':1,'extraSourceCasts':0,'spentUses':1,'mpSpent':0,'enemyDamage':0,
        'convertedGaugeGain':20,'observedGauge':{'before':before_lb,'after':after_lb},
        'gaugeAdaptation':'FFBE crystal units use the converter\'s capped native-gauge percentage; this is not a full native gauge refill.',
        'sourceSkillStartNotifications':4,'stockDefendStartNotifications':4,'stockDefendUsesSameOpportunity':True,
        'originalSaveFilesUnchanged':True,'existingGamePackagesUnchanged':True,'temporaryInstallationRemoved':True,
        'productionAvailabilityPayloadsReleased':0,
        'limitations':['One source ability and ordinary actor/selection fixture; general lifecycle/loadout remains unbound.',
            'Repeat, multicast, dual-wield and rendered-menu behavior are not certified by this case.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'))
    (OUT/'native-source-availability-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))
