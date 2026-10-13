"""Verify a spent FFBE use survives native owner death and revival."""
from verify_combat_observation import diagnostic_skill_id
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
from verify_combat_observation import OUT,read_json,sha
from verify_source_observation import SOURCE,verify_source_artifacts
import make_vision_mod as generator
from life_controls import add_controls


def verify(directory,build):
    skill_id = diagnostic_skill_id(directory)
    run,fixture,profile,plan,gate,runtime=verify_source_artifacts(directory,build,SOURCE,'limited',owned=True,life=True)
    assert gate['kind']=='limited' and gate['maximumUses']==1 and gate['raw']==[0,3,157,[516017,0,1,1,1,1,0,1,0]]
    tables={}
    def table(name):return tables.setdefault(name,{'add':[],'set':[]})
    expected_controls=add_controls(table,[],profile,skill_id=skill_id)
    assert fixture['lifeControls']==expected_controls
    cooked=read_json(Path(fixture['directory'])/'cooked-skill-rows.json')['rows']
    for control in expected_controls:
        expected=deepcopy(generator.row_by('Skill/DT_SkillData','ID',control['templateId'])[1]);expected.update(control['set'])
        assert all(cooked[control['rowName']][key]==value for key,value in expected.items() if key not in ('Name','Description'))
        effect=generator.row_by('Skill/DT_SkillEffectData','ID',control['effectId'])[1]
        assert effect['EffectType']==('InstantDeath' if control['skillId']==(skill_id+20) else 'Revival')
    grants=fixture['nativeGrants'];assert len(grants)==2 and {g['unitId'] for g in grants}=={1001,1002}
    for grant in grants:
        name={1001:'Rain',1002:'Lasswell'}[grant['unitId']]
        assert grant['table']==f'Unit/LevelParameter/Playable/DT_UnitLevelParameter{name}' and grant['row']=='1'
        original=generator.rows(grant['table']);assert original['1']['AddSkills']==grant['before'] and grant['before'][-1]==-1
        assert grant['after']==grant['before'][:-1]+[skill_id,{1001:(skill_id+20),1002:(skill_id+40)}[grant['unitId']]]
        expected=deepcopy(original);expected['1']['AddSkills']=grant['after']
        path=directory/f"native-grant-{grant['unitId']}.json"
        assert sha(path)==grant['cookedSha256'] and read_json(path)['rows']==expected
    log_path=directory/'collected-ue4ss/UE4SS.log';log=log_path.read_text(encoding='utf8',errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=','turn_owner_failed=','owned_binding_failed','transient_skill_list_requested'))
    assert log.count('life_complete source_casts=2 deaths=1 revivals=1')==log.count('converted_observation_complete')==1
    assert log.count(f'life_controls_verified death={skill_id+20} revival={skill_id+40}')==1
    events=[]
    for line_number,line in enumerate(log.splitlines(),1):
        match=re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$',line)
        if match:events.append({**json.loads(match[2]),'logLine':line_number})
    counts=Counter(e['event'] for e in events)
    assert counts['registered']==13 and counts['native_attached']==counts['owned_enforcement_attached']==counts['owned_battle']==1
    assert counts['owned_registered']==counts['owned_selection']==counts['owned_authorization']==counts['native_guard']==2
    assert not any(counts[k] for k in ('native_attach_failed','registration_failed','read_failed','trace_capacity','query_capacity','native_observation_capacity','owned_query_capacity'))
    def select(name):return [e for e in events if e['event']==name]
    begin=select('owned_battle')[0]
    assert begin['before'] is False and begin['after'] is True and begin['callerRva']==0x4fc7e0f
    assert select('native_attached')[0]['mode']=='enforce_fixture'
    attached=select('owned_enforcement_attached')[0]
    assert attached['allowed'] and attached['skillId']==skill_id and attached['command']==SOURCE
    owners={r['unitId']:r for r in select('owned_registered')}
    assert set(owners)=={1001,1002}
    assert all(len({r[field] for r in owners.values()})==2 for field in ('owner','actor','parameter','uniqueId'))
    results=[]
    for unit,owner in owners.items():
        assert owner['command']==SOURCE and owner['visionId']==-1
        assert {skill_id,400010,{1001:(skill_id+20),1002:(skill_id+40)}[unit]}<=set(owner['skills'])
        auth=[e for e in select('owned_authorization') if e['owner']==owner['owner']];assert len(auth)==1;auth=auth[0]
        selection=[e for e in select('owned_selection') if e['owner']==owner['owner']];assert len(selection)==1;selection=selection[0]
        guards=[e for e in select('native_guard') if e['actor']==owner['actor']];assert len(guards)==1;guard=guards[0]
        assert auth['decision'] and auth['nativeAllowed'] and auth['reason']=='committed' and auth['usedBefore']==0 and auth['usedAfter']==1
        assert guard['nativeAllowed'] and guard['skillId']==skill_id and guard['job']==guard['rootJob']==auth['job']
        assert guard['actionCount']==guard['targetCount']==1 and selection['cast']==auth['cast']
        assert selection['uniqueId']==selection['target']==owner['uniqueId'] and selection['turn']==1
        assert begin['logLine']<owner['logLine']<selection['logLine']<guard['logLine']<auth['logLine']
        turns=[e for e in select('owned_turn') if e['owner']==owner['owner']]
        assert len(turns)>=2 and [t['ordinal'] for t in turns]==list(range(1,len(turns)+1))
        assert all(t['actor']==owner['actor'] and t['uniqueId']==owner['uniqueId'] and t['owned'] for t in turns)
        assert turns[0]['used']==0 and all(t['used']==1 for t in turns[1:])
        resources=re.findall(fr'life_source_result unit={unit} before_lb=(\d+) after_lb=(\d+) mp=(\d+)',log)
        assert len(resources)==1
        before,after,mp=map(int,resources[0]);assert after-before==20
        samples=re.findall(fr'life_sample unit={unit} actor=(\d+) turn=(\d+) hp=(\d+) max_hp=(\d+) mp=(\d+) lb=(\d+) dead=(true|false)',log)
        assert samples and all(int(s[0])==owner['actor'] and int(s[4])==mp for s in samples)
        if unit==1002:assert all(s[-1]=='false' and int(s[2])>0 for s in samples)
        results.append({'unitId':unit,'owner':owner['owner'],'actor':owner['actor'],'parameter':owner['parameter'],
            'uniqueId':owner['uniqueId'],'turns':turns,'gaugeBefore':before,'gaugeAfter':after,'spentUses':1,'mpSpent':0})
    rain,reviver=owners[1001],owners[1002]
    life=select('owned_life');assert life,'No authoritative death-state binding observed'
    alive_by_owner={r['owner']:True for r in owners.values()};transitions=[]
    for event in life:
        owner=owners[event['unitId']]
        assert event['owner']==owner['owner'] and event['actor']==owner['actor'] and event['parameter']==owner['parameter']
        assert event['uniqueId']==owner['uniqueId'] and event['used']==1 and not event['available']
        assert event['aliveBefore']==alive_by_owner[owner['owner']]
        if event['alive']!=event['aliveBefore']:
            assert owner==rain;transitions.append(event)
        alive=event['alive']
        alive_by_owner[owner['owner']]=alive
        assert event['hp']>0 if alive else event['hp']==0
        assert event['reason']==('uses_exhausted' if alive else 'owner_dead')
        assert any(e['payload']==event['payload'] and e['uniqueId']==owner['uniqueId'] for e in select('dead_state'))
    assert [e['alive'] for e in transitions]==[False,True]
    death,revival=transitions
    commands=select('command_decide');counts_by_skill=Counter()
    for command_index,command in enumerate(commands):
        assert len(command['actions'])==1 and not command['notConsume']
        action=command['actions'][0];skill=action['skillId'];counts_by_skill[skill]+=1
        assert not action['item'] and skill in (skill_id,(skill_id+20),(skill_id+40),400010)
        owner=rain if action['uniqueId']==rain['uniqueId'] else reviver
        assert action['uniqueId']==owner['uniqueId']
        target=rain['uniqueId'] if skill==(skill_id+40) else action['uniqueId']
        assert action['targets']==[target]
        if skill==(skill_id+20):assert owner==rain and command['logLine']<death['logLine']
        if skill==(skill_id+40):assert owner==reviver and death['logLine']<command['logLine']<revival['logLine']
        end_line=commands[command_index+1]['logLine'] if command_index+1<len(commands) else len(log.splitlines())+1
        messages=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra')
            and e['skillId']==skill and e['uniqueId']==action['uniqueId'] and command['logLine']<e['logLine']<end_line]
        assert len(messages)==4 and len({e['payload'] for e in messages})==1
        assert all(e['owner']['actorAddress']==owner['actor'] and e['targets']==[target] for e in messages)
    assert counts_by_skill[skill_id]==2 and counts_by_skill[(skill_id+20)]==counts_by_skill[(skill_id+40)]==1
    assert counts_by_skill[400010]>=2
    starts=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra')]
    for skill,count in counts_by_skill.items():
        messages=[e for e in starts if e['skillId']==skill]
        assert len(messages)==count*4 and len({e['payload'] for e in messages})==count
    queries=[e for e in select('owned_menu_query') if e['uniqueId']==rain['uniqueId']]
    death_command=next(c for c in commands if c['actions'][0]['skillId']==(skill_id+20))
    assert any(not e['decision'] and not e['nativeAllowed'] and death_command['logLine']<e['logLine']<revival['logLine'] for e in queries)
    assert any(e['nativeAllowed'] and not e['decision'] and e['reason']=='uses_exhausted' and e['used']==1
        and e['turn']>=3 and e['logLine']>revival['logLine'] for e in queries)
    assert any(c['actions'][0]['uniqueId']==rain['uniqueId'] and c['actions'][0]['skillId']==400010 and c['logLine']>revival['logLine'] for c in commands)
    revived=re.findall(r'life_revived unit=1001 unique=(\d+) turn=(\d+) hp=(\d+) max_hp=(\d+)',log);assert len(revived)==1
    unique,turn,hp,max_hp=map(int,revived[0]);assert unique==rain['uniqueId'] and hp>0 and revival['hp']==max_hp
    assert log.count('life_dead unit=1001 ')==1 and 'life_source_blocked unit=1001 turn=3 revived=true' in log
    return {'status':'passed','scope':'native_death_and_revival_preserve_spent_source_use','run':directory.name,
        'runSha256':sha(directory/'run.json'),'logSha256':sha(log_path),'source':SOURCE,'sourceRule':gate,
        'sourcePlanSha256':sha(directory/'availability-plan.json'),'sourceContractSha256':sha(runtime/'source_contract.lua'),
        'owners':results,'lifeTransitions':transitions,'revivalHitPoints':hp,'nativeControls':expected_controls,
        'sourceCasts':2,'spentUsePreserved':True,'sameOwnerAfterRevival':True,'consecutiveOwnerTurns':True,
        'nativeBridgeDllSha256':build['dllSha256'],'canonicalRuntimeSha256':sha(runtime/'availability.lua'),
        'canonicalHostSha256':sha(runtime/'native_host.lua'),'fixtureDllSha256':read_json(directory/'fixture-build.json')['dllSha256'],
        'originalSaveFilesUnchanged':True,'existingGamePackagesUnchanged':True,'temporaryInstallationRemoved':True,
        'productionAvailabilityPayloadsReleased':0,
        'limitations':['One ordinary owner death/revival path with native control skills, not FFBE death/revival conversion certification.',
            'Battle end/reset, actor replacement, late grants and additional cast forms remain unbound.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'))
    (OUT/'native-life-source-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))
