"""Verify one native selection with and without a mastered RepeatAction passive."""
import argparse
from collections import Counter
from copy import deepcopy
import json
import re
import sys
from verify_combat_observation import OUT, ROOT, diagnostic_skill_id, read_json, sha
from verify_fire_observation import verify_fire_artifacts
sys.path.insert(0, str(ROOT/'tools'))
import make_vision_mod as generator


def verify(directory, build, *, control=False, suppressed=False):
    skill = diagnostic_skill_id(directory)
    assert skill == 900010
    run, fixture, profile = verify_fire_artifacts(directory, build, repeat=True, repeat_control=control, repeat_suppressed=suppressed)
    assert not run.get('fixtureFailed') and not run.get('timeoutTerminated')
    assert profile['supported'] and not profile['issues']
    assert not any(fixture[k] for k in ('nativeOwnedSource', 'nativeVisionSource', 'nativeLifeSource', 'nativeMultiCommand'))
    assert len(fixture['nativeGrants']) == 1
    grant = fixture['nativeGrants'][0]
    assert grant['unitId'] == 1001 and grant['table'] == 'Unit/LevelParameter/Playable/DT_UnitLevelParameterRain'
    assert grant['row'] == '1' and grant['level'] == 1
    expected = deepcopy(generator.rows(grant['table']))
    assert expected['1']['AddSkills'] == grant['before'] and grant['before'][-1] == -1
    assert grant['after'] == grant['before'][:-1]+[skill]+([] if control else [90000])
    expected['1']['AddSkills'] = grant['after']
    cooked = directory/'native-grant-1001.json'
    assert sha(cooked) == grant['cookedSha256'] and read_json(cooked)['rows'] == expected
    passive = fixture['nativeRepeatPassive']
    assert (passive['id'], passive['templateId'], passive['templateEffectId'], passive['row']) == (90000,1414,1012,'FFRNativeRepeatProbe')
    expected = deepcopy(generator.rows('Skill/DT_PassiveSkillData'))
    donor = deepcopy(generator.row_by('Skill/DT_PassiveSkillData','ID',1414)[1])
    bundle = deepcopy(donor['effectBundleList'][0]); bundle['effectId'] = 1012
    assert passive['set'] == {'ID':90000,'SortId':90000,'Name':'Native repeat observation',
                              'Description':'Temporary automatic-repeat diagnostic.','effectBundleList':[bundle]}
    donor.update(passive['set']); expected[passive['row']] = donor
    cooked = directory/'native-repeat-passive.json'
    assert sha(cooked) == passive['cookedSha256']
    observed = read_json(cooked)['rows']
    # Cooked FText carries its own representation; all behavioral fields and
    # every unchanged stock row must still match the source tables exactly.
    assert {k:v for k,v in observed.items() if k != passive['row']} == generator.rows('Skill/DT_PassiveSkillData')
    assert all(observed[passive['row']][k] == v for k,v in donor.items() if k not in ('Name','Description'))
    assert fixture['expectedRow']['belongCommandList'] == [1]
    effect = generator.row_by('Skill/DT_SkillEffectData','ID',1012)[1]
    assert effect['EffectType'] == 'RepeatAction'
    assert effect['ParamList'] == [1,0,-1,-1,-1,-1,100,-1,1,-1,0,-1,-1,-1,-1]
    assert effect['effectEndActionNum'] == 2
    general = deepcopy(generator.rows('Skill/Other/DT_SkillGeneralData'))
    assert skill not in general['NewRow']['nonRepeatSkillsIds']
    if suppressed:
        # The production command materializer already routes its caster-side
        # gauge effect through the equipping actor in every Fire fixture.
        assert skill not in general['NewRow']['equipperActionVisionSkills']
        general['NewRow']['equipperActionVisionSkills'].append(skill)
        general['NewRow']['nonRepeatSkillsIds'].append(skill)
        cooked = directory/'native-repeat-general.json'
        assert sha(cooked) == fixture['cookedGeneralSha256'] and read_json(cooked)['rows'] == general
    else:
        assert fixture['cookedGeneralSha256'] is None
    driver = directory/'Mods/FFRBattleProbe/Scripts/repeat_driver.lua'
    driver_text = driver.read_text(encoding='utf8')
    assert ':SetUsableActiveSkill' not in driver_text and ':RefreshCommandSkill' not in driver_text
    assert driver_text.count(':DecideActionKey(') == driver_text.count(':DecideTarget(') == 1
    log_path = directory/'collected-ue4ss/UE4SS.log'
    log = log_path.read_text(encoding='utf8',errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=', 'turn_owner_failed=', 'read_failed=', 'owned_binding_failed'))
    assert log.count('fire_row_verified') == log.count('passive_row_verified id=90000 effect=1012 category=3') == 1
    assert log.count('repeat_complete ') == log.count('converted_observation_complete') == log.count('command_returned') == 1
    master = re.findall(r'master_passive_grants unit=1001 before=([\d,]*) after=([\d,]*)',log)
    assert master == [('', '' if control else '90000')]
    owned = re.findall(r'native_owned active=([\d,]*) passives=([\d,]*)',log)
    assert len(owned) == 1 and skill in list(map(int,owned[0][0].split(',')))
    assert owned[0][1] == ('' if control else '90000')
    effects = re.findall(r'repeat_effect id=(\d+) life=(\d+) actor=(\d+) target=(\d+) type=(\S+)',log)
    assert effects == ([] if control else [('1012','1','1001','1001','CPP_ContFxRepeatAction')])
    events = []
    for number,line in enumerate(log.splitlines(),1):
        match = re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$',line)
        if match: events.append({**json.loads(match[2]),'logLine':number})
    def named(name): return [e for e in events if e['event']==name]
    counts = Counter(e['event'] for e in events)
    assert counts['registered']==13 and counts['native_attached']==1 and named('native_attached')[0]['mode']=='observe'
    assert not any(counts[k] for k in ('native_attach_failed','registration_failed','read_failed','trace_capacity',
                                      'query_capacity','native_observation_capacity','repeat_stack'))
    decisions = named('command_decide')
    assert len(decisions)==1 and decisions[0]['commandId']==-1 and not decisions[0]['notConsume']
    assert decisions[0]['actions']==[{'item':False,'skillId':skill,'targets':[1],'uniqueId':0}]
    fields = ('owner','skill','target','hp','mp','lb','enemyHp','turn')
    requests = re.findall(r'command_requested owner=(\d+) skill=(\d+) target=(\d+) hp=(\d+) mp=(\d+) lb=(\d+) enemy_hp=(\d+) turn=(\d+)',log)
    assert len(requests)==1
    before = dict(zip(fields,map(int,requests[0])))
    assert (before['owner'],before['skill'],before['target'],before['enemyHp'],before['turn']) == (0,skill,1,200,1)
    samples=[]
    for number,line in enumerate(log.splitlines(),1):
        match = re.search(r'sample begins=(\d+) hp=(\d+) mp=(\d+) lb=(\d+) enemy_hp=(\d+) turn=(\d+) fire=(\d+)',line)
        if match: samples.append(dict(zip(('begins','hp','mp','lb','enemyHp','turn','fire'),map(int,match.groups())),logLine=number))
    single = control or suppressed
    casts=1 if single else 2
    guards=[e for e in named('native_guard') if e['skillId']==skill]
    assert len(guards)==casts and len({g['job'] for g in guards})==len({g['objectIndex'] for g in guards})==casts
    assert len({g['actor'] for g in guards})==1 and guards[0]['actor']>0
    assert all(g['nativeAllowed'] and g['job']==g['rootJob'] and g['actionCount']==g['targetCount']==1 for g in guards)
    assert decisions[0]['logLine']<guards[0]['logLine']
    starts=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra') and e['skillId']==skill]
    assert len(starts)==4*casts and len({s['payload'] for s in starts})==casts
    for index,guard in enumerate(guards):
        end=guards[index+1]['logLine'] if index+1<casts else float('inf')
        group=[e for e in starts if guard['logLine']<e['logLine']<end]
        assert len(group)==4 and len({e['payload'] for e in group})==1
        assert all(e['targets']==[1] and e['uniqueId']==0 and e['owner']['unitId']==1001
                   and e['owner']['actorAddress']==guard['actor'] for e in group)
    beginnings=re.findall(r'cast_begin ordinal=(\d+) unique=(\d+) payload=(.*)',log)
    assert [int(b[0]) for b in beginnings]==list(range(1,casts+1)) and all(b[1]=='0' for b in beginnings)
    assert len({b[2] for b in beginnings})==casts
    assert len(samples)>=3 and all(s['fire']==1 for s in samples)
    final=samples[-1]
    assert final['begins']==casts and final['mp']==before['mp']-4*casts and final['lb']>=before['lb']+4*casts
    assert 0<final['enemyHp']<before['enemyHp'] and guards[-1]['logLine']<final['logLine']
    assert all({k:v for k,v in s.items() if k!='logLine'}=={k:v for k,v in final.items() if k!='logLine'} for s in samples[-3:])
    if not single:
        interim=[s for s in samples if guards[0]['logLine']<s['logLine']<guards[1]['logLine']]
        assert interim and all(s['begins']==1 and s['mp']==before['mp']-4 and s['lb']==before['lb']+4 for s in interim)
        assert final['enemyHp']<interim[-1]['enemyHp']<200
    other=[e for e in named('native_guard') if decisions[0]['logLine']<e['logLine']<final['logLine'] and e['actor']!=guards[0]['actor']]
    isolated=samples[0] if single else final
    if single:
        assert len(other)<=1 and all(e['skillId']==500060 and isolated['logLine']<e['logLine'] for e in other)
        assert isolated['begins']==1 and isolated['hp']==before['hp'] and isolated['lb']==before['lb']+4
        assert isolated['turn']==1 and final['turn']==2
        if other: assert 0<final['hp']<before['hp'] and final['lb']>isolated['lb']
        else: assert final['hp']==before['hp'] and final['lb']==isolated['lb']
        assert all(s['mp']==before['mp']-4 and s['enemyHp']==isolated['enemyHp'] for s in samples)
    else:
        assert not other and all(s['hp']==before['hp'] and s['turn']==1 for s in samples)
    result=re.findall(r'repeat_complete begins=(\d+) before_mp=(\d+) after_mp=(\d+) before_lb=(\d+) after_lb=(\d+) before_hp=(\d+) after_hp=(\d+) before_enemy_hp=(\d+) after_enemy_hp=(\d+) before_turn=(\d+) after_turn=(\d+)',log)
    assert len(result)==1 and tuple(map(int,result[0]))==(casts,before['mp'],final['mp'],before['lb'],final['lb'],before['hp'],final['hp'],before['enemyHp'],final['enemyHp'],1,final['turn'])
    return {'status':'passed','scope':'native_repeat_suppressed' if suppressed else 'native_repeat_control' if control else 'native_automatic_repeat',
            'run':directory.name,'runSha256':sha(directory/'run.json'),'logSha256':sha(log_path),'driverSha256':sha(driver),
            'nativeBridgeDllSha256':build['dllSha256'],
            'canonicalRuntimeSha256':sha(directory/'Mods/FFRAvailabilityRuntime/Scripts/availability.lua'),
            'canonicalHostSha256':sha(directory/'Mods/FFRAvailabilityRuntime/Scripts/native_host.lua'),
            'skillId':skill,'source':fixture['source'],'sourceProfileSha256':fixture['profileSha256'],
            'passiveLearnedAndMastered':not control,'passiveActive':not control,'nativeGrant':grant,
            'nativeRepeatExcluded':suppressed,
            'explicitSelections':1,'commandDecision':decisions[0],'nativeGuards':guards,'nativeCasts':casts,
            'totalMpSpent':4*casts,'before':before,'afterCast':isolated,'settled':final,'repeatStackEvents':0,
            'originalSaveFilesUnchanged':True,'existingGamePackagesUnchanged':True,'temporaryInstallationRemoved':True,
            'availabilityHoldsReleased':0,'limitations':[
                'One stock RepeatAction configuration, one actor and one converted spell; this is not a dual-wield test.',
                'Automatic casts have independent root jobs and no repeat-stack event in this trace.',
                'The production availability selection/lifecycle binder remains unbound.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');parser.add_argument('--control',action='store_true');parser.add_argument('--suppressed',action='store_true');args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'),control=args.control,suppressed=args.suppressed)
    name='native-repeat-suppressed-validation.json' if args.suppressed else 'native-repeat-control-validation.json' if args.control else 'native-repeat-validation.json'
    (OUT/name).write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))
