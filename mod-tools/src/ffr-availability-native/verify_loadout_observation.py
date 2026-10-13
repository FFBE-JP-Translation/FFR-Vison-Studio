"""Verify late native Vision grants and removal/regrant without resetting uses."""
from verify_combat_observation import diagnostic_skill_id
import argparse
from collections import Counter
import json
import re
from verify_combat_observation import OUT, read_json, sha
from verify_source_observation import SOURCE, verify_source_artifacts
from verify_owned_observation import verify_grants


def verify(directory, build):
    skill_id = diagnostic_skill_id(directory)
    run, fixture, profile, plan, gate, runtime = verify_source_artifacts(
        directory, build, SOURCE, 'limited', owned=True, vision=True, loadout=True)
    assert gate['kind'] == 'limited' and gate['maximumUses'] == 1 and gate['childId'] == '516017'
    assert gate['raw'] == [0, 3, 157, [516017, 0, 1, 1, 1, 1, 0, 1, 0]]
    grants = verify_grants(directory, fixture, vision=True)
    assert fixture['expectedRow']['belongCommandList'] == [1]
    assert profile['timeline']['hitFrames'] == [10]
    effects = profile['conversion']['native']['effects']
    assert len(effects) == 1 and effects[0]['set']['EffectType'] == 'ParameterVariation'
    assert effects[0]['set']['ParamList'] == [20, 4, 2, -1, 0, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1]
    for name in ('owned_driver.lua', 'loadout_driver.lua'):
        driver = (directory/'Mods/FFRBattleProbe/Scripts'/name).read_text(encoding='utf8')
        assert ':SetUsableActiveSkill' not in driver and ':RefreshCommandSkill' not in driver
    log_path = directory/'collected-ue4ss/UE4SS.log'
    log = log_path.read_text(encoding='utf8', errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=', 'turn_owner_failed=', 'owned_binding_failed', 'transient_skill_list_requested'))
    assert log.count('owned_row_verified source='+SOURCE) == 1
    assert log.count('loadout_complete owners=2 source_casts=2') == log.count('converted_observation_complete') == 1
    assert log.count('debug_equipment_context_prepared') == log.count('vision_initial_units count=8') == 1
    assert 'vision_equipped ' not in log
    events = []
    for number, line in enumerate(log.splitlines(), 1):
        match = re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$', line)
        if match:
            events.append({**json.loads(match[2]), 'logLine': number})
    counts = Counter(e['event'] for e in events)
    assert counts['registered'] == 13
    assert counts['native_attached'] == counts['owned_enforcement_attached'] == counts['owned_battle'] == 1
    assert counts['owned_registered'] == counts['owned_selection'] == counts['owned_authorization'] == counts['native_guard'] == 2
    assert counts['owned_loadout'] == 6
    assert not any(counts[k] for k in ('native_attach_failed', 'registration_failed', 'read_failed', 'trace_capacity', 'query_capacity', 'native_observation_capacity', 'owned_query_capacity'))
    def all_events(name): return [e for e in events if e['event'] == name]
    begin = all_events('owned_battle')[0]
    assert begin['before'] is False and begin['after'] is True and begin['callerRva'] == 0x4fc7e0f
    assert all_events('native_attached')[0]['mode'] == 'enforce_fixture'
    attached = all_events('owned_enforcement_attached')[0]
    assert attached['allowed'] and attached['skillId'] == skill_id and attached['command'] == SOURCE and attached['gate'] == gate['key']
    registered = all_events('owned_registered')
    assert {r['unitId'] for r in registered} == {1001, 1002}
    assert all(len({r[k] for r in registered}) == 2 for k in ('owner', 'actor', 'parameter', 'uniqueId'))
    assert all(r['command'] == SOURCE and not r['owned'] and r['visionId'] == -1
               and skill_id not in r['skills'] and 400010 in r['skills'] and begin['logLine'] < r['logLine'] for r in registered)
    commands = all_events('command_decide')
    assert len(commands) == 6 and all(len(c['actions']) == 1 and not c['actions'][0]['item'] for c in commands)
    starts = [e for e in events if e['event'] in ('skill_begin_message', 'skill_begin_libra')]
    results = []
    for r in registered:
        unit, owner, actor, unique, parameter = (r[k] for k in ('unitId', 'owner', 'actor', 'uniqueId', 'parameter'))
        vision = {1001: 13017, 1002: 13045}[unit]
        assert log.count(f'vision_deferred unit={unit} vision={vision} equipment=-1') == 1
        assert log.count(f'vision_inventory vision={vision} before=0 after=1') == 1
        assert log.count(f'equipment_context unit={unit} during_encount=true native_parameter={parameter} battle_parameter={parameter} native_vision=-1') == 1
        assert log.count(f'equipment_set_result unit={unit} initial_vision={vision} battle_vision={vision} owned=true') == 1
        for text in (f'initial_unowned unit={unit} unique={unique} turn=1',
                     f'granted unit={unit} unique={unique} turn=2 vision={vision} actor={actor} parameter={parameter}',
                     f'removed unit={unit} unique={unique} turn=3 vision=-1',
                     f'regranted_exhausted unit={unit} unique={unique} turn=3 vision={vision}'):
            assert log.count(text) == 1, text
        turns = [e for e in all_events('owned_turn') if e['owner'] == owner]
        assert len(turns) >= 3 and [e['ordinal'] for e in turns] == list(range(1, len(turns)+1))
        assert all(e['actor'] == actor and e['unitId'] == unit and e['uniqueId'] == unique for e in turns)
        assert all(not e['owned'] and e['used'] == -1 and e['visionId'] == -1 for e in turns[:2])
        assert all(e['owned'] and e['used'] == 1 and e['visionId'] == vision for e in turns[2:])
        changes = [e for e in all_events('owned_loadout') if e['owner'] == owner]
        assert [(e['before'], e['owned'], e['used'], e['turn'], e['visionId']) for e in changes] == [
            (False, True, 0, 2, vision), (True, False, 1, 3, -1), (False, True, 1, 3, vision)]
        assert all(e['actor'] == actor and e['parameter'] == parameter and e['unitId'] == unit
                   and e['uniqueId'] == unique and e['origin'] == 'query' and (skill_id in e['skills']) == e['owned'] for e in changes)
        assert changes[1]['skills'] == r['skills'] and changes[0]['skills'] == changes[2]['skills']
        queries = [e for e in all_events('owned_menu_query') if e['owner'] == owner]
        assert queries and all(e['actor'] == actor and e['unitId'] == unit and e['uniqueId'] == unique and e['skillId'] == skill_id for e in queries)
        for q in queries:
            if q['logLine'] < changes[0]['logLine']:
                assert not q['owned'] and not q['decision'] and q['reason'] == 'unowned_command' and q['used'] == -1
            elif not q['owned']:
                assert changes[1]['logLine'] < q['logLine'] < changes[2]['logLine']
                assert not q['decision'] and q['reason'] == 'unowned_command' and q['used'] == 1
            elif q['turn'] >= 3:
                assert q['nativeAllowed'] and not q['decision'] and q['reason'] == 'uses_exhausted' and q['used'] == 1
        selected = [e for e in all_events('owned_selection') if e['owner'] == owner]
        auth = [e for e in all_events('owned_authorization') if e['owner'] == owner]
        guards = [e for e in all_events('native_guard') if e['actor'] == actor]
        assert len(selected) == len(auth) == len(guards) == 1
        selected, auth, guard = selected[0], auth[0], guards[0]
        assert selected['turn'] == 2 and selected['uniqueId'] == selected['target'] == unique
        assert selected['actor'] == auth['actor'] == actor and selected['unitId'] == auth['unitId'] == unit
        assert selected['cast'] == auth['cast'] and auth['job'] == guard['job'] == guard['rootJob']
        assert auth['nativeAllowed'] and auth['decision'] and auth['reason'] == 'committed' and auth['usedBefore'] == 0 and auth['usedAfter'] == 1
        assert guard['nativeAllowed'] and guard['skillId'] == skill_id and guard['actionCount'] == guard['targetCount'] == 1
        own_commands = [c for c in commands if c['actions'][0]['uniqueId'] == unique]
        assert [c['actions'][0]['skillId'] for c in own_commands] == [400010, skill_id, 400010]
        assert all(c['actions'][0]['targets'] == [unique] for c in own_commands)
        assert turns[1]['logLine'] < changes[0]['logLine'] < selected['logLine'] < guard['logLine'] < auth['logLine'] < turns[2]['logLine'] < changes[1]['logLine'] < changes[2]['logLine'] < own_commands[2]['logLine']
        assert own_commands[0]['logLine'] < changes[0]['logLine'] and own_commands[1]['logLine'] < guard['logLine']
        assert any(q['nativeAllowed'] and q['decision'] and q['reason'] == 'available' and q['used'] == 0
                   and changes[0]['logLine'] < q['logLine'] < auth['logLine'] for q in queries)
        assert any(not q['owned'] and changes[1]['logLine'] < q['logLine'] < changes[2]['logLine'] for q in queries)
        assert any(q['owned'] and not q['decision'] and changes[2]['logLine'] < q['logLine'] < own_commands[2]['logLine'] for q in queries)
        for skill, count in ((skill_id, 1), (400010, 2)):
            messages = [e for e in starts if e['skillId'] == skill and e['owner']['actorAddress'] == actor]
            assert len(messages) == 4*count and len({e['payload'] for e in messages}) == count
            assert all(e['uniqueId'] == unique and e['targets'] == [unique] for e in messages)
            if skill == skill_id: assert all(auth['logLine'] < e['logLine'] < changes[1]['logLine'] for e in messages)
        resources = re.findall(fr'source_result unit={unit} turn=(\d+) before_lb=(\d+) after_lb=(\d+) mp=(\d+)', log)
        assert len(resources) == 1
        turn, before, after, mp = map(int, resources[0])
        assert turn == 2 and after-before == 20
        samples = [tuple(map(int, s)) for s in re.findall(fr'sample unit={unit} turn=(\d+) hp=(\d+) mp=(\d+) lb=(\d+)', log)]
        assert samples and all(s[1] > 0 and s[2] == mp for s in samples)
        loadouts = re.findall(fr'turn_owner_loadout unique={unique} actor={actor} unit={unit} active=([^\s]*) with_vision=([^\s]*)', log)
        assert len(loadouts) >= 3 and all(str(skill_id) not in active.split(',') for active, inclusive in loadouts)
        assert all(str(skill_id) not in inclusive.split(',') for active, inclusive in loadouts[:2])
        assert all(str(skill_id) in inclusive.split(',') for active, inclusive in loadouts[2:])
        results.append({'unitId': unit, 'owner': owner, 'actor': actor, 'parameter': parameter, 'uniqueId': unique,
                        'visionId': vision, 'changes': changes, 'turns': turns, 'queries': queries,
                        'gaugeBefore': before, 'gaugeAfter': after, 'mpSpent': 0, 'spentUsesAfterRegrant': 1})
    return {'status': 'passed', 'scope': 'native_late_vision_grants_and_spent_use_preserved_on_regrant', 'run': directory.name,
            'runSha256': sha(directory/'run.json'), 'logSha256': sha(log_path), 'source': SOURCE, 'sourceRule': gate,
            'sourcePlanSha256': sha(directory/'availability-plan.json'), 'sourceContractSha256': sha(runtime/'source_contract.lua'),
            'nativeGrants': grants, 'owners': results, 'acceptedCasts': 2, 'loadoutChanges': 6,
            'ownershipGetter': 'CPP_BtlUnitParameter.GetActiveSkillListWithVision', 'temporaryUsableListUsed': False,
            'nativeBridgeDllSha256': build['dllSha256'], 'canonicalRuntimeSha256': sha(runtime/'availability.lua'),
            'canonicalHostSha256': sha(runtime/'native_host.lua'), 'fixtureDllSha256': read_json(directory/'fixture-build.json')['dllSha256'],
            'originalSaveFilesUnchanged': True, 'existingGamePackagesUnchanged': True, 'temporaryInstallationRemoved': True,
            'productionAvailabilityPayloadsReleased': 0,
            'limitations': ['The debug arena requires a fixture-only map encounter flag before native equipment APIs resolve the battle actors.',
                            'Native SetEquipmentId/UnequipmentId and skill getters are exercised; normal field equipment UI and rendered menus are not inspected.',
                            'Two stable actors and one limited-use source are exercised; replacement actors and additional cast forms remain unbound.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('run'); args = parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}', args.run)
    report = verify(OUT/'native-battle-runs'/args.run, read_json(OUT/'native-bridge-validation.json'))
    (OUT/'native-loadout-source-validation.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps(report, indent=2))
