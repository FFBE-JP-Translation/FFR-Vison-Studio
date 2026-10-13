"""Schedule and independent readback checks for the opt-in cinematic stage."""
import ast
import copy
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffbe_presentation as presentation
import ffbe_resonance


def fixture():
    plan = ffbe_resonance.schedule(2., 1, 7, {'moveType': 1},
                                  movement={'target_offset': [12., 34., 56.]})
    placement = {'mode': 'target_stage', 'backdrop': 'native_subspace',
                 'sourceOffset': [-96, 84], 'camera': {'sourceCenter': [-96, 84],
                     'unitsPerPixel': 3.5, 'runtimeScale': .8, 'focalLength': 75}}
    visuals = [{'name': 'back', 'asset': '/Game/back', 'anchor': 'screen',
                'placement': copy.deepcopy(placement), 'layer': 2, 'frame': 0, 'frames': 150},
               {'name': 'caster', 'asset': '/Game/caster', 'anchor': 'caster',
                'layer': 1, 'frame': 0, 'frames': 90},
               {'name': 'front', 'asset': '/Game/front', 'anchor': 'screen',
                'placement': copy.deepcopy(placement), 'layer': 1, 'frame': 5, 'frames': 160}]
    return plan, {'_hostResonance': True, 'visuals': visuals, 'reconstructionProfile': {
        'casterPlacement': 'approach_target', 'screenPlacement': placement}}


def bytype(plan, kind):
    return [(e['time'], e['set']) for e in plan['events'] if e['set']['EventType'] == kind]


def verify(entry, result):
    # Load only the production readback verifier; avoid .NET and unrelated
    # builder/audio dependencies. Its input has native sparse field semantics.
    path = Path(__file__).resolve().parents[1] / 'private/verify_ffbe_presentation.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'verify_host_placement')
    namespace = {'presentation': presentation, 'math': math}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), namespace)
    events = [(e['time'], copy.deepcopy(e['set'])) for e in result['events']]
    for _, e in events:
        if e['EventType'] == 'BGChange':
            e['BG_Change_BackgroundLevel'] = 'soft:'+e['BG_Change_BackgroundLevel']
    return namespace['verify_host_placement'](entry, events, 7, result['duration'])


class TargetStage(unittest.TestCase):
    def test_all_layers_share_approach_and_source_clocks_remain_exact(self):
        plan, entry = fixture()
        before = copy.deepcopy((plan, entry))
        out = presentation.apply(plan, entry, [], 7)
        self.assertEqual(before, (plan, entry))
        source = presentation.action_start(plan)
        self.assertEqual(source, presentation.action_start(out))
        self.assertEqual(bytype(plan, 'OtherReaction'), bytype(out, 'OtherReaction'))
        moves = bytype(out, 'SsActorMoveToTargetToSsID')
        self.assertEqual(len(moves), 3)
        for i, fx in enumerate(entry['visuals']):
            aid = f'FFBE_7_{i}'
            spawn, data = next((t, e['SsActor_SsData']) for t, e in bytype(out, 'SsActorSpawnSpriteStudioActor')
                               if e['SsActor_SsData']['spriteStudioID'] == aid)
            self.assertEqual(spawn, source+fx['frame']*400-800)
            self.assertTrue(data['bDisableFollowing'])
            self.assertFalse(data['bSpawnRelativeTarget'])
            time, e = next((t, e) for t, e in moves if e['SsActor_MoveToTarget_ID'] == aid)
            self.assertEqual(time, spawn+2)
            self.assertEqual(e['SsActor_MoveToTarget_targetPointID'], -1)
            self.assertEqual(e['SsActor_MoveToTarget_partName'], 'Null_root')
            self.assertEqual(e['SsActor_MoveToTarget_plusOffset'],
                             {'x': 12.+(-8 if fx['layer'] == 1 else 8), 'y': 34., 'z': 56.})
            self.assertEqual(next(t for t, e in bytype(out, 'SsActorDestroyToSsID')
                                  if e['SsActor_Destroy_ID'] == aid), spawn+fx['frames']*400)
        self.assertTrue(verify(entry, out)['targetStageVerified'])

    def test_camera_conversion_visibility_and_cleanup(self):
        plan, entry = fixture()
        out = presentation.apply(plan, entry, [], 7)
        first = min(t for t, _ in bytype(out, 'SsActorSpawnSpriteStudioActor'))
        last = max(t for t, _ in bytype(out, 'SsActorDestroyToSsID'))
        look = bytype(out, 'CameraSetLookAtTarget')
        self.assertEqual(len(look), 1)
        self.assertEqual(look[0][0], first-3)
        self.assertEqual(look[0][1]['Camera_SetLookAtTarget_Id'], -1)
        center = look[0][1]['Camera_SetLookAtTarget_AddLocation']
        for axis, value in zip('xyz', (12., 34.-96*3.5*.8, 56.+84*3.5*.8)):
            self.assertAlmostEqual(center[axis], value)
        zoom = bytype(out, 'CameraSetZoomInOut')
        self.assertEqual(len(zoom), 1)
        self.assertEqual(zoom[0][0], first-2)
        self.assertEqual(zoom[0][1]['Camera_SetZoomInOut_Value'], 75)
        self.assertFalse(zoom[0][1]['Camera_SetZoomInOut_RelativeValue'])
        self.assertEqual(bytype(out, 'UnitSetVisibility'), [])
        self.assertEqual(bytype(out, 'BGRevert')[0][0], last+400)
        self.assertTrue(any(t > last for t, _ in bytype(out, 'CameraSetDefault')))
        reset_fields = [e for _, e in bytype(out, 'CameraSetDefault')]
        self.assertEqual(reset_fields[0], reset_fields[-1])
        self.assertEqual(reset_fields[-1]['Camera_SetDefault_Frame'], 0)
        self.assertFalse(any(first <= t <= last for t, _ in bytype(out, 'CameraSetDefault')))
        self.assertLess(max(e['time'] for e in out['events']), out['duration'])

    def test_enemy_visibility_policy_keeps_all_friendly_categories_visible(self):
        plan, entry = fixture()
        entry['reconstructionProfile']['screenPlacement']['hideEnemies'] = True
        for fx in entry['visuals']:
            if fx['anchor'] == 'screen': fx['placement']['hideEnemies'] = True
        out = presentation.apply(plan, entry, [], 7)
        events = bytype(out, 'UnitSetVisibility')
        self.assertEqual(len(events), 2)
        for category in ('ActionUnit', 'FriendUnits', 'VisionUnits', 'BeastUnits'):
            self.assertTrue(events[0][1]['Unit_SetVisibility_Is'+category])
        for category in ('TargetUnit', 'EnemyUnits'):
            self.assertFalse(events[0][1]['Unit_SetVisibility_Is'+category])
        self.assertTrue(verify(entry, out)['targetStageVerified'])
        bad = copy.deepcopy(out)
        next(e for e in bad['events'] if e['set']['EventType'] == 'UnitSetVisibility')['set']['Unit_SetVisibility_IsFriendUnits'] = False
        with self.assertRaises(AssertionError): verify(entry, bad)

    def test_optional_layer_depth_changes_only_stage_actor_depths(self):
        plan, entry = fixture()
        baseline = presentation.apply(plan, entry, [], 7)
        entry['reconstructionProfile']['screenPlacement']['layerDepth'] = {'back': 64, 'front': -32}
        for fx in entry['visuals']:
            if fx['anchor'] == 'screen':
                fx['placement']['layerDepth'] = {'back': 64, 'front': -32}
        out = presentation.apply(plan, entry, [], 7)
        self.assertTrue(verify(entry, out)['targetStageVerified'])
        comparable = copy.deepcopy(out)
        for i, fx in enumerate(entry['visuals']):
            aid = f'FFBE_7_{i}'
            depth = -32 if fx['layer'] == 1 else 64
            old_depth = -8 if fx['layer'] == 1 else 8
            for event in comparable['events']:
                fields = event['set']
                if fields.get('SsActor_SsData', {}).get('spriteStudioID') == aid:
                    self.assertEqual(fields['SsActor_SsData']['addLocation']['x'], depth)
                    fields['SsActor_SsData']['addLocation']['x'] = old_depth
                if fields.get('SsActor_MoveToTarget_ID') == aid:
                    self.assertEqual(fields['SsActor_MoveToTarget_plusOffset']['x'], 12+depth)
                    fields['SsActor_MoveToTarget_plusOffset']['x'] = 12+old_depth
        self.assertEqual(comparable, baseline)
        with self.assertRaises(AssertionError):
            verify(entry, baseline)  # The cooked check rejects stale +/-8 offsets.
        placement = entry['reconstructionProfile']['screenPlacement']
        for depths in (None, {}, {'back': 0, 'front': -32}, {'back': -64, 'front': -32},
                       {'back': 64, 'front': 0}, {'back': 64, 'front': 32},
                       {'back': math.inf, 'front': -32}, {'back': 64, 'front': math.nan},
                       {'back': True, 'front': -32}, {'back': 64, 'front': '-32'}):
            with self.subTest(depths=depths), self.assertRaises(ValueError):
                presentation.validate_screen_placement({**placement, 'layerDepth': depths})

    def test_profile_rejects_nonfinite_invalid_and_overflowing_optics(self):
        _, entry = fixture()
        valid = entry['reconstructionProfile']['screenPlacement']
        for field in ('focalLength', 'runtimeScale', 'unitsPerPixel'):
            for value in (0, -1, True, '75', math.nan, math.inf):
                bad = copy.deepcopy(valid); bad['camera'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    presentation.validate_screen_placement(bad)
        for center in (None, [0], [0, math.inf], [False, 0], [1e308, 0]):
            bad = copy.deepcopy(valid); bad['camera']['sourceCenter'] = center
            with self.subTest(center=center), self.assertRaises(ValueError):
                presentation.validate_screen_placement(bad)
        for field in ('camera', 'backdrop'):
            bad = copy.deepcopy(valid); bad.pop(field)
            with self.assertRaises(ValueError): presentation.validate_screen_placement(bad)

    def test_stage_requires_completed_approach_and_matching_screen_profile(self):
        plan, entry = fixture()
        missing = copy.deepcopy(entry); missing['reconstructionProfile'].pop('casterPlacement')
        with self.assertRaisesRegex(ValueError, 'approach_target'):
            presentation.apply(plan, missing, [], 7)
        mismatch = copy.deepcopy(entry); mismatch['visuals'][0]['placement']['camera']['focalLength'] = 76
        with self.assertRaisesRegex(ValueError, 'differs'):
            presentation.apply(plan, mismatch, [], 7)
        early = copy.deepcopy(plan)
        approach = next(e for e in early['events'] if e['set']['EventType'] == 'UnitMoveToTarget')
        first = presentation.action_start(early)-800
        approach['time'] = first-12*400-2  # complete before spawn, but after camera setup
        with self.assertRaisesRegex(ValueError, 'camera setup'):
            presentation.apply(early, entry, [], 7)

    def test_readback_rejects_missing_screen_move_relative_lens_and_missing_restore(self):
        plan, entry = fixture(); good = presentation.apply(plan, entry, [], 7)
        bad = copy.deepcopy(good)
        bad['events'] = [e for e in bad['events'] if e['set'].get('SsActor_MoveToTarget_ID') != 'FFBE_7_0']
        with self.assertRaises(AssertionError): verify(entry, bad)
        bad = copy.deepcopy(good)
        next(e for e in bad['events'] if e['set']['EventType'] == 'CameraSetZoomInOut')['set']['Camera_SetZoomInOut_RelativeValue'] = True
        with self.assertRaises(AssertionError): verify(entry, bad)
        bad = copy.deepcopy(good)
        bad['events'].append({'time': 12000, 'set': {'EventType': 'UnitSetVisibility', 'Unit_SetVisibility_IsActionUnit': False}})
        with self.assertRaises(AssertionError): verify(entry, bad)


if __name__ == '__main__':
    unittest.main()
