"""Verify native W Action batch identity, cost reservation and cancellation."""
from verify_combat_observation import diagnostic_skill_id
import argparse
from collections import Counter
from copy import deepcopy
import json
import re
import sys
from verify_combat_observation import OUT, ROOT, read_json, sha
from verify_fire_observation import verify_fire_artifacts
sys.path.insert(0, str(ROOT/'tools'))
import make_vision_mod as generator


def verify(directory, build, *, cancel=False):
    skill_id = diagnostic_skill_id(directory)
    run, fixture, profile = verify_fire_artifacts(directory, build, multi=True, multi_cancel=cancel)
    assert not run.get('fixtureFailed') and not run.get('timeoutTerminated')
    assert profile['supported'] and not profile['issues']
    assert not fixture['nativeOwnedSource'] and not fixture['nativeVisionSource'] and not fixture['nativeLifeSource']
    assert len(fixture['nativeGrants']) == 1
    grant = fixture['nativeGrants'][0]
    assert grant['unitId'] == 1001 and grant['table'] == 'Unit/LevelParameter/Playable/DT_UnitLevelParameterRain'
    assert grant['row'] == '1' and grant['level'] == 1
    expected = deepcopy(generator.rows(grant['table']))
    assert expected['1']['AddSkills'] == grant['before'] and grant['before'][-1] == -1
    assert grant['after'] == grant['before'][:-1]+[skill_id]
    expected['1']['AddSkills'] = grant['after']
    cooked = directory/'native-grant-1001.json'
    assert sha(cooked) == grant['cookedSha256'] and read_json(cooked)['rows'] == expected
    assert fixture['expectedRow']['belongCommandList'] == [1]
    general = generator.rows('Skill/Other/DT_SkillGeneralData')['NewRow']
    assert general['wActionSkillId'] == 400710 and 400710 in general['sequentialSelectedSkills']
    wrapper = generator.row_by('Skill/DT_SkillData', 'ID', 400710)[1]
    assert wrapper['Cost'] == 0 and all(e['effectId'] == -1 for e in wrapper['effectBundleList'])
    driver = directory/'Mods/FFRBattleProbe/Scripts/multicommand_driver.lua'
    driver_text = driver.read_text(encoding='utf8')
    assert ':SetUsableActiveSkill' not in driver_text and ':RefreshCommandSkill' not in driver_text
    log_path = directory/'collected-ue4ss/UE4SS.log'
    log = log_path.read_text(encoding='utf8', errors='replace')
    assert not any(s in log for s in ('combat_driver_failed=', 'turn_owner_failed=', 'read_failed=', 'owned_binding_failed'))
    assert log.count('fire_row_verified') == log.count('multicommand_complete') == log.count('converted_observation_complete') == 1
    events = []
    for number, line in enumerate(log.splitlines(), 1):
        match = re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$', line)
        if match: events.append({**json.loads(match[2]), 'logLine': number})
    def named(name): return [e for e in events if e['event'] == name]
    counts = Counter(e['event'] for e in events)
    assert counts['registered'] == 13 and counts['native_attached'] == 1
    assert named('native_attached')[0]['mode'] == 'observe'
    assert not any(counts[k] for k in ('native_attach_failed', 'registration_failed', 'read_failed', 'trace_capacity', 'query_capacity', 'native_observation_capacity', 'repeat_stack'))
    master = re.findall(r'master_grants unit=1001 before=([\d,]*) after=([\d,]*)', log)
    assert len(master) == 1
    before, after = (list(map(int, s.split(','))) if s else [] for s in master[0])
    granted = [400710,skill_id] if skill_id == 900010 else [400710]
    assert not set(granted).intersection(before) and after == sorted(before+granted)
    ownership = re.findall(r'native_owned unit=1001 skills=([\d,]+)', log)
    assert len(ownership) == (2 if cancel else 1)
    assert all(400710 in list(map(int, s.split(','))) and skill_id in list(map(int, s.split(','))) for s in ownership)
    decisions = named('command_decide')
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision['commandId'] == -1 and not decision['notConsume']
    assert decision['actions'] == [{'item': False, 'skillId': 400710, 'targets': [0], 'uniqueId': 0},
                                   {'item': False, 'skillId': skill_id, 'targets': [1], 'uniqueId': 0},
                                   {'item': False, 'skillId': skill_id, 'targets': [1], 'uniqueId': 0}]
    selections = []
    samples = []
    stacks = []
    costs = []
    cancellations = []
    for number, line in enumerate(log.splitlines(), 1):
        match = re.search(r'select ordinal=(\d+) unique=(\d+) skill=(\d+) target=(\d+) turn=(\d+)', line)
        if match: selections.append(dict(zip(('ordinal', 'uniqueId', 'skillId', 'target', 'turn'), map(int, match.groups())), logLine=number))
        match = re.search(r'sample phase=(\d+) turn=(\d+) hp=(\d+) mp=(\d+) lb=(\d+) enemy_hp=(\d+) fire=(\d+)', line)
        if match: samples.append(dict(zip(('phase', 'turn', 'hp', 'mp', 'lb', 'enemyHp', 'fire'), map(int, match.groups())), logLine=number))
        match = re.search(r'stack phase=(\w+) count=(\d+) state=(-?\d+) key=(-?\d+) index=(-?\d+) parent=(-?\d+) next=(-?\d+) node=(-?\d+)', line)
        if match: stacks.append(dict(zip(('count', 'state', 'key', 'index', 'parent', 'next', 'node'), map(int, match.groups()[1:])), phase=match[1], logLine=number))
        match = re.search(r'stack_mp phase=(\w+) getter=(\d+) raw=(\d+) display=(\d+)', line)
        if match: costs.append(dict(zip(('getter', 'raw', 'display'), map(int, match.groups()[1:])), phase=match[1], logLine=number))
        match = re.search(r'cancel_verified turn=(\d+) mp=(\d+) hp=(\d+) lb=(\d+) enemy_hp=(\d+)', line)
        if match: cancellations.append(dict(zip(('turn', 'mp', 'hp', 'lb', 'enemyHp'), map(int, match.groups())), logLine=number))
    assert [s['ordinal'] for s in selections] == ([1, 1, 2] if cancel else [1, 2])
    assert all(s['uniqueId'] == 0 and s['skillId'] == skill_id and s['target'] == s['turn'] == 1 for s in selections)
    assert all(s['logLine'] < decision['logLine'] for s in selections)
    baseline = next(s for s in samples if s['phase'] == 1)
    assert baseline['enemyHp'] == 200 and baseline['fire'] == 0 and baseline['hp'] > 0
    assert len(costs) == len(stacks) and [c['phase'] for c in costs] == [s['phase'] for s in stacks]
    assert all(c['getter'] == c['raw'] == c['display'] for c in costs)
    expected_cost = {'before_root': 0, 'after_root': 0, 'selected_1': 0, 'targeted_1': 4,
                     'before_cancel': 4, 'cancel_1': 4, 'cancel_2': 0, 'cancel_3': 0, 'selected_2': 4, 'targeted_2': 0}
    assert all(c['raw'] == baseline['mp']-expected_cost[c['phase']] for c in costs)
    assert [s['phase'] for s in stacks] == (['before_root', 'after_root', 'selected_1', 'targeted_1', 'before_cancel', 'cancel_1', 'cancel_2', 'cancel_3'] if cancel else []) + ['before_root', 'after_root', 'selected_1', 'targeted_1', 'selected_2', 'targeted_2']
    expected_stack = {'before_root': (0, -1, -1, -1), 'after_root': (1, 400710, 0, -1),
                      'selected_1': (2, skill_id, 1, 0), 'targeted_1': (3, 400710, 0, -1),
                      'before_cancel': (3, 400710, 0, -1), 'cancel_1': (2, skill_id, 1, 0),
                      'cancel_2': (1, 400710, 0, -1), 'cancel_3': (0, -1, -1, -1),
                      'selected_2': (4, skill_id, 3, 0), 'targeted_2': (0, -1, -1, -1)}
    assert all(tuple(s[k] for k in ('count', 'key', 'index', 'parent')) == expected_stack[s['phase']] for s in stacks)
    target_complete = costs[-1]
    assert target_complete['phase'] == 'targeted_2' and decision['logLine'] < target_complete['logLine']
    guards = [e for e in named('native_guard') if e['skillId'] in (400710, skill_id)]
    assert [g['skillId'] for g in guards] == [400710, skill_id, skill_id]
    assert len({g['actor'] for g in guards}) == 1 and guards[0]['actor'] > 0
    assert len({g['job'] for g in guards}) == len({g['objectIndex'] for g in guards}) == 3
    assert all(g['nativeAllowed'] and g['job'] == g['rootJob'] and g['actionCount'] == g['targetCount'] == 1 for g in guards)
    assert target_complete['logLine'] < guards[0]['logLine']
    starts = [e for e in events if e['event'] in ('skill_begin_message', 'skill_begin_libra') and e['skillId'] in (400710, skill_id)]
    assert len(starts) == 12 and len({e['payload'] for e in starts}) == 3
    for index, guard in enumerate(guards):
        next_line = guards[index+1]['logLine'] if index < 2 else float('inf')
        group = [e for e in starts if guard['logLine'] < e['logLine'] < next_line]
        assert len(group) == 4 and len({e['payload'] for e in group}) == 1
        assert all(e['skillId'] == guard['skillId'] and e['uniqueId'] == 0 and e['targets'] == ([0] if index == 0 else [1])
                   and e['owner']['unitId'] == 1001 and e['owner']['actorAddress'] == guard['actor'] for e in group)
    assert len({e['owner']['sourceParameterAddress'] for e in starts}) == 1
    interim = [s for s in samples if guards[1]['logLine'] < s['logLine'] < guards[2]['logLine']]
    assert interim and all(s['turn'] == 1 and s['mp'] == baseline['mp']-4 and 0 < s['enemyHp'] < 200 and s['fire'] == 1 for s in interim)
    final = samples[-1]
    assert final['phase'] == 3 and final['turn'] == 1 and final['mp'] == baseline['mp']-8 and 0 < final['enemyHp'] < interim[-1]['enemyHp']
    assert final['fire'] == 1 and final['lb'] > baseline['lb'] and final['logLine'] > guards[-1]['logLine']
    assert samples[-2]['enemyHp'] == final['enemyHp'] and samples[-2]['mp'] == final['mp']
    assert not [e for e in named('native_guard') if selections[0]['logLine'] < e['logLine'] < final['logLine'] and e['actor'] != guards[0]['actor']]
    assert len(cancellations) == int(cancel)
    if cancel:
        cancelled = cancellations[0]
        assert cancelled['turn'] == 1 and all(cancelled[k] == baseline[k] for k in ('mp', 'hp', 'lb', 'enemyHp'))
        assert selections[0]['logLine'] < cancelled['logLine'] < selections[1]['logLine']
        assert not [e for e in events if selections[0]['logLine'] < e['logLine'] < cancelled['logLine'] and e['event'] in ('command_decide', 'native_guard', 'skill_begin_message', 'skill_begin_libra')]
    return {'status': 'passed', 'scope': 'native_w_action_partial_selection_cancellation' if cancel else 'native_w_action_two_converted_fire_casts',
            'run': directory.name, 'runSha256': sha(directory/'run.json'), 'logSha256': sha(log_path), 'driverSha256': sha(driver),
            'nativeBridgeDllSha256': build['dllSha256'], 'fixtureDllSha256': read_json(directory/'fixture-build.json')['dllSha256'],
            'canonicalRuntimeSha256': sha(directory/'Mods/FFRAvailabilityRuntime/Scripts/availability.lua'),
            'canonicalHostSha256': sha(directory/'Mods/FFRAvailabilityRuntime/Scripts/native_host.lua'),
            'source': fixture['source'], 'skillId': skill_id, 'sourceProfileSha256': fixture['profileSha256'], 'nativeGrant': grant,
            'nativeMasterGrants': {'before':before,'after':after,'added':granted},
            'nativeActiveCategoryVerified': skill_id == 900010,
            'commandDecision': decision, 'nativeGuards': guards, 'selectedFireCasts': 2, 'skillStartNotifications': 12,
            'wrapperAndChildrenHaveDistinctRootJobs': True, 'nativeSelectionReservations': costs,
            'nativeCommandStack': stacks, 'cancellations': cancellations, 'totalMpSpent': 8,
            'enemyHpBefore': baseline['enemyHp'], 'enemyHpAfterFirstCast': interim[-1]['enemyHp'], 'enemyHpAfterBothCasts': final['enemyHp'],
            'gaugeBefore': baseline['lb'], 'gaugeAfter': final['lb'], 'selectionReservationRefundedBeforeNativeExecution': True,
            'originalSaveFilesUnchanged': True, 'existingGamePackagesUnchanged': True, 'temporaryInstallationRemoved': True,
            'availabilityHoldsReleased': 0,
            'limitations': ['Two explicit W Action child selections are distinct casts; this does not exercise automatic repeats or dual wield.',
                            'The native runtime observes these jobs; no availability-gate selection binder is enabled.',
                            'Native raw, ordinary and displayed MP reserve during partial selection and refund on cancellation/final dispatch; no custom refund is applied.',
                            'One actor and converted Fire are exercised; rendered menus and full action coverage remain unverified.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('run'); parser.add_argument('--cancel', action='store_true'); args = parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}', args.run)
    report = verify(OUT/'native-battle-runs'/args.run, read_json(OUT/'native-bridge-validation.json'), cancel=args.cancel)
    name = 'native-multicommand-cancel-validation.json' if args.cancel else 'native-multicommand-validation.json'
    (OUT/name).write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps(report, indent=2))
