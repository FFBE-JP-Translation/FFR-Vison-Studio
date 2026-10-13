"""Verify native skill ownership and independent uses on two equipping actors."""
from verify_combat_observation import diagnostic_skill_id
import argparse
from collections import Counter
from copy import deepcopy
import json
import re
from verify_combat_observation import OUT,read_json,sha
from verify_source_observation import SOURCE,verify_source_artifacts
import make_vision_mod as generator


def verify_grants(directory,fixture,*,vision=False):
    skill_id = diagnostic_skill_id(directory)
    grants=fixture['nativeGrants'];assert len(grants)==2 and {g['unitId'] for g in grants}=={1001,1002}
    if vision:
        relative='Item/Vision/DT_VisionAwakeningMasteryData'
        original=generator.rows(relative);expected=deepcopy(original)
        for grant in grants:
            assert grant['kind']=='vision_mastery' and grant['visionId']=={1001:13017,1002:13045}[grant['unitId']]
            assert grant['table']==relative and grant['level']==0
            row=original[grant['row']]
            assert row['ID']==grant['visionId'] and row['Level']==0 and row['detailData']==grant['before']
            assert grant['before'][-1]=={'parameterType':'None','params':[-1,-1]}
            assert grant['after']==grant['before'][:-1]+[{'parameterType':'ActiveSkill','params':[skill_id,-1]}]
            expected[grant['row']]['detailData']=grant['after']
        for grant in grants:
            cooked=directory/f"native-grant-{grant['unitId']}.json"
            assert sha(cooked)==grant['cookedSha256'] and read_json(cooked)['rows']==expected
        general=directory/'native-general.json';assert sha(general)==fixture['cookedGeneralSha256']
        expected_general=deepcopy(generator.rows('Skill/Other/DT_SkillGeneralData'))
        expected_general['NewRow']['equipperActionVisionSkills'].append(skill_id)
        assert read_json(general)['rows']==expected_general,'Vision fixture changed unrelated general fields'
    for grant in grants:
        if vision:continue
        name={1001:'Rain',1002:'Lasswell'}[grant['unitId']]
        assert grant['table']==f'Unit/LevelParameter/Playable/DT_UnitLevelParameter{name}'
        assert grant['row']=='1' and grant['level']==1
        original=generator.rows(grant['table'])
        assert original['1']['AddSkills']==grant['before'] and grant['before'][-1]==-1
        assert grant['after']==grant['before'][:-1]+[skill_id]
        cooked=directory/f"native-grant-{grant['unitId']}.json"
        assert sha(cooked)==grant['cookedSha256']
        expected=deepcopy(original);expected['1']['AddSkills']=grant['after']
        assert read_json(cooked)['rows']==expected,'Grant altered another native level field'
    return grants


def verify(directory,build,*,vision=False,cancel=False):
    skill_id = diagnostic_skill_id(directory)
    run,fixture,profile,plan,gate,runtime=verify_source_artifacts(directory,build,SOURCE,'limited',owned=True,vision=vision,cancel=cancel)
    assert gate['kind']=='limited' and gate['maximumUses']==1 and gate['childId']=='516017'
    assert gate['raw']==[0,3,157,[516017,0,1,1,1,1,0,1,0]]
    assert fixture['expectedRow']['belongCommandList']==[1]
    grants=verify_grants(directory,fixture,vision=vision)
    # This case uses actual learned skills, with no temporary allowed-list call.
    driver=(directory/'Mods/FFRBattleProbe/Scripts/owned_driver.lua').read_text(encoding='utf8')
    assert ':SetUsableActiveSkill' not in driver and ':RefreshCommandSkill' not in driver
    log_path=directory/'collected-ue4ss/UE4SS.log';log=log_path.read_text(encoding='utf8',errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=','turn_owner_failed=','owned_binding_failed','transient_skill_list_requested'))
    assert log.count('owned_row_verified source='+SOURCE)==1
    assert log.count('owned_cast_requested ')==log.count('owned_cast_returned ')==log.count('owned_result ')==2
    assert log.count('owned_complete owners=2 source_casts=2 enemy_hp=200')==log.count('converted_observation_complete')==1
    if vision:
        assert log.count('vision_inventory vision=13017 before=0 after=1')==log.count('vision_inventory vision=13045 before=0 after=1')==1
        assert log.count('vision_initial_units count=8')==1
        for unit,vision_id in ((1001,13017),(1002,13045)):
            assert log.count(f'vision_equipped unit={unit} vision={vision_id} before=-1 after={vision_id}')==1
    events=[]
    for line_number,line in enumerate(log.splitlines(),1):
        match=re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$',line)
        if match:events.append({**json.loads(match[2]),'logLine':line_number})
    counts=Counter(e['event'] for e in events)
    assert counts['registered']==13 and counts['native_attached']==counts['owned_enforcement_attached']==counts['owned_battle']==1
    assert counts['owned_registered']==counts['owned_selection']==counts['owned_authorization']==counts['native_guard']==2
    assert not any(counts[k] for k in ('native_attach_failed','registration_failed','read_failed','trace_capacity','query_capacity','native_observation_capacity','owned_query_capacity'))
    def all_events(name):return [e for e in events if e['event']==name]
    def one(name):return all_events(name)[0]
    assert one('native_attached')['mode']=='enforce_fixture'
    attached=one('owned_enforcement_attached')
    assert attached['allowed'] and attached['skillId']==skill_id and attached['command']==SOURCE and attached['gate']==gate['key']
    begin=one('owned_battle')
    assert begin['before'] is False and begin['after'] is True and begin['callerRva']==0x4fc7e0f
    registered=all_events('owned_registered')
    assert {r['unitId'] for r in registered}=={1001,1002}
    assert all(r['command']==SOURCE and skill_id in r['skills'] and 400010 in r['skills'] for r in registered)
    assert all(len({r[key] for r in registered})==2 for key in ('owner','actor','parameter','uniqueId'))
    by_unit={r['unitId']:r for r in registered}
    cancellations=[]
    if cancel:
        pattern=r'owned_cancel phase=(\w+) unit=(\d+) unique=(\d+) turn=(\d+) state=(-?\d+) key=(-?\d+) index=(-?\d+) stack=(\d+) node=(-?\d+) hp=(\d+) mp=(\d+) lb=(\d+)'
        for number,line in enumerate(log.splitlines(),1):
            match=re.search(pattern,line)
            if match:
                fields=dict(zip(('unitId','uniqueId','turn','state','key','index','stack','node','hp','mp','lb'),map(int,match.groups()[1:])))
                cancellations.append({'phase':match[1],**fields,'logLine':number})
        assert len(cancellations)==8
    assert all(begin['logLine']<r['logLine'] for r in registered)
    authorizations=all_events('owned_authorization');selections=all_events('owned_selection');guards=all_events('native_guard')
    assert len({s['cast'] for s in selections})==len({s['payload'] for s in selections})==2
    assert all(e['nativeAllowed'] and e['decision'] and e['reason']=='committed'
        and e['usedBefore']==0 and e['usedAfter']==1 for e in authorizations)
    assert all(g['nativeAllowed'] and g['skillId']==skill_id and g['job']==g['rootJob']
        and g['actionCount']==g['targetCount']==1 for g in guards)
    commands=all_events('command_decide')
    assert all(len(c['actions'])==1 and not c['actions'][0]['item'] for c in commands)
    cast_commands=[c for c in commands if c['actions'][0]['skillId']==skill_id]
    defend_commands=[c for c in commands if c['actions'][0]['skillId']==400010]
    assert len(cast_commands)==2 and len(defend_commands)>=2 and len(commands)==2+len(defend_commands)
    starts=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra')]
    results=[]
    for unit,registered_owner in by_unit.items():
        owner=registered_owner['owner'];actor=registered_owner['actor'];unique=registered_owner['uniqueId']
        if vision:assert registered_owner['visionId']=={1001:13017,1002:13045}[unit]
        auth=[e for e in authorizations if e['owner']==owner];selected=[e for e in selections if e['owner']==owner]
        assert len(auth)==len(selected)==1
        auth,selected=auth[0],selected[0]
        guard=[e for e in guards if e['actor']==actor];assert len(guard)==1;guard=guard[0]
        assert auth['actor']==selected['actor']==actor and auth['unitId']==selected['unitId']==unit
        assert auth['cast']==selected['cast'] and auth['job']==guard['job']
        assert selected['uniqueId']==selected['target']==unique and selected['turn']==1
        command=[c for c in cast_commands if c['actions'][0]['uniqueId']==unique];assert len(command)==1;command=command[0]
        assert command['actions'][0]['targets']==[unique]
        assert max(command['logLine'],selected['logLine'])<guard['logLine']<auth['logLine']
        turns=[e for e in all_events('owned_turn') if e['owner']==owner]
        assert len(turns)>=2 and [e['ordinal'] for e in turns]==list(range(1,len(turns)+1))
        assert all(e['owned'] and e['actor']==actor and e['unitId']==unit and e['uniqueId']==unique for e in turns)
        if vision:assert all(e['visionId']==registered_owner['visionId'] for e in turns)
        assert turns[0]['used']==0 and all(e['used']==1 for e in turns[1:])
        queries=[e for e in all_events('owned_menu_query') if e['owner']==owner]
        assert all(e['actor']==actor and e['uniqueId']==unique and e['owned'] for e in queries)
        assert any(e['nativeAllowed'] and e['decision'] and e['reason']=='available' and e['used']==0
            and e['turn']==1 and e['logLine']<auth['logLine'] for e in queries)
        assert any(e['nativeAllowed'] and not e['decision'] and e['reason']=='uses_exhausted' and e['used']==1
            and e['turn']>=2 and e['logLine']>auth['logLine'] for e in queries)
        if cancel:
            phases=[e for e in cancellations if e['unitId']==unit]
            assert [e['phase'] for e in phases]==['before','selected','returned','verified']
            before,chosen,returned,verified=phases
            assert all(e['uniqueId']==unique and e['turn']==1 for e in phases)
            assert chosen['key']==skill_id and chosen['stack']==before['stack']+1
            assert all(verified[k]==before[k] for k in ('state','key','index','stack','hp','mp','lb'))
            assert all(e[k]==before[k] for e in phases for k in ('hp','mp','lb'))
            assert verified['logLine']<selected['logLine']
            assert any(q['nativeAllowed'] and q['decision'] and q['used']==0 and q['reason']=='available'
                and returned['logLine']<q['logLine']<verified['logLine'] for q in queries)
            assert not any(before['logLine']<e['logLine']<verified['logLine'] for e in events
                if e['event'] in ('command_decide','owned_selection','owned_authorization','native_guard','skill_begin_message','skill_begin_libra'))
        own_defends=[c for c in defend_commands if c['actions'][0]['uniqueId']==unique]
        assert own_defends and all(c['actions'][0]['targets']==[unique] and c['logLine']>auth['logLine'] for c in own_defends)
        for skill,count in ((skill_id,1),(400010,len(own_defends))):
            messages=[e for e in starts if e['skillId']==skill and e['owner']['actorAddress']==actor]
            assert len(messages)==count*4 and len({e['payload'] for e in messages})==count
            assert all(e['uniqueId']==unique and e['targets']==[unique] for e in messages)
        resource=re.findall(fr'owned_result unit={unit} turn=(\d+) before_lb=(\d+) after_lb=(\d+) mp=(\d+)',log)
        assert len(resource)==1
        turn,before,after,mp=map(int,resource[0]);assert turn==1 and after-before==20
        samples=[tuple(map(int,s)) for s in re.findall(fr'owned_sample unit={unit} turn=(\d+) hp=(\d+) mp=(\d+) lb=(\d+)',log)]
        assert samples and all(s[1]>0 and s[2]==mp for s in samples)
        loadouts=re.findall(fr'turn_owner_loadout unique={unique} actor={actor} unit={unit} active=([^\s]*) with_vision=([^\s]*)',log)
        assert loadouts and all((str(skill_id) in active.split(','))==(not vision) and str(skill_id) in inclusive.split(',')
            for active,inclusive in loadouts)
        results.append({'unitId':unit,'owner':owner,'actor':actor,'uniqueId':unique,'registeredNativeSkills':registered_owner['skills'],
            'authorizations':1,'spentUses':1,'gaugeBefore':before,'gaugeAfter':after,'mpSpent':0,
            'nativeDefendCommands':len(own_defends),'turns':turns,'queries':queries})
        if vision:results[-1]['equippedVisionId']=registered_owner['visionId']
    return {'status':'passed','scope':'native_command_cancel_preserves_two_source_uses' if cancel else 'native_vision_grant_with_two_independent_equipping_actors' if vision else 'native_learned_skill_with_two_independent_equipping_actors','run':directory.name,
        'runSha256':sha(directory/'run.json'),'logSha256':sha(log_path),'source':SOURCE,'sourceRule':gate,
        'sourcePlanSha256':sha(directory/'availability-plan.json'),'sourceContractSha256':sha(runtime/'source_contract.lua'),
        'nativeGrants':grants,'owners':results,'acceptedCasts':2,'ownerStateIndependent':True,
        'equippedVisionGrant':vision,
        'cancellations':cancellations,'cancelledSelections':2 if cancel else 0,
        'cancellationStage':'before_native_command_decision' if cancel else 'not_exercised',
        'ownershipGetter':'CPP_BtlUnitParameter.GetActiveSkillListWithVision','temporaryUsableListUsed':False,
        'nativeBridgeDllSha256':build['dllSha256'],'canonicalRuntimeSha256':sha(runtime/'availability.lua'),
        'canonicalHostSha256':sha(runtime/'native_host.lua'),'fixtureDllSha256':read_json(directory/'fixture-build.json')['dllSha256'],
        'originalSaveFilesUnchanged':True,'existingGamePackagesUnchanged':True,'temporaryInstallationRemoved':True,
        'productionAvailabilityPayloadsReleased':0,
        'limitations':['Two equipped Visions grant the skill exclusively through the Vision-inclusive getter; the native equipper-action binding executes on the ordinary owners.' if vision else 'Native ownership and per-actor uses are verified for two ordinary actors, without an equipped Vision.',
            'Late grants, actor replacement, full battle lifecycle and additional cast forms remain unbound.',
            'This reads the command view model; the rendered menu has not been visually inspected.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--vision',action='store_true');mode.add_argument('--cancel',action='store_true');args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'),vision=args.vision,cancel=args.cancel)
    (OUT/('native-cancel-source-validation.json' if args.cancel else 'native-vision-source-validation.json' if args.vision else 'native-owned-source-validation.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))
