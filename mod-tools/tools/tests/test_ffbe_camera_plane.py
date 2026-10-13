"""Screen placement contracts; native Kismet cooking is verified separately."""
from copy import deepcopy
import math
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffbe_presentation as presentation


def placement():
    return {'mode': 'camera_plane', 'sourceOffset': [0, 0],
            'referenceStage': [320, 320], 'runtimeScale': .8,
            'overscan': [1.06, 1.06], 'cameraDepth': {'front': 1000, 'rearMargin': 300}}


def fixture():
    plan = {'duration': 120000, 'events': [
        {'time': 12000, 'set': {'EventType': 'UnitPlayAnimByName',
                              'Unit_PlayAnimByName_AnimationName': 'LB1'}},
        {'time': 48000, 'set': {'EventType': 'OtherReaction', 'Marker': 'source final hit'}}]}
    visuals = [{'name': 'rear', 'asset': '/Game/rear', 'anchor': 'screen',
                'layer': 2, 'frame': 5, 'frames': 64, 'placement': placement()},
               {'name': 'front', 'asset': '/Game/front', 'anchor': 'screen',
                'layer': 1, 'frame': 30, 'frames': 42, 'placement': placement()},
               {'name': 'caster', 'asset': '/Game/caster', 'anchor': 'caster',
                'layer': 1, 'frame': 0, 'frames': 90}]
    return plan, {'visuals': visuals}, [
        {'frame': 90, 'bank': 'SE', 'cueName': 'final_blow', 'durationMs': 200}]


class CameraPlane(unittest.TestCase):
    def test_action_background_preserves_cast_and_source_clocks(self):
        plan, entry, sounds = fixture()
        for event in plan['events']: event['time'] += 48000
        entry['reconstructionProfile'] = {'screenPlacement': {**placement(), 'backdrop':'native_subspace'}}
        opening = presentation.apply(plan, entry, sounds, 7)
        entry['reconstructionProfile']['screenPlacement']['backdropTiming'] = 'action'
        action = presentation.apply(plan, entry, sounds, 7)
        setup = lambda e:e['set']['EventType'].startswith('OtherChangeSubSpace') or e['set']['EventType']=='BGChange'
        self.assertEqual([e for e in opening['events'] if not setup(e)], [e for e in action['events'] if not setup(e)])
        first_spawn = min(e['time'] for e in action['events'] if e['set']['EventType']=='SsActorSpawnSpriteStudioActor')
        background = next(e['time'] for e in action['events'] if e['set']['EventType']=='BGChange')
        self.assertGreater(background, 48000)
        self.assertLess(background, first_spawn)

    def test_flash_plane_can_share_projection_without_owning_background_replacement(self):
        plan, entry, sounds = fixture()
        entry['reconstructionProfile'] = {'screenPlacement': {**placement(), 'backdrop': 'native_subspace'}}
        output = presentation.apply(plan, entry, sounds, 7)
        kinds = [event['set']['EventType'] for event in output['events']]
        self.assertEqual(kinds.count('BGChange'), 1)
        self.assertEqual(kinds.count('BGRevert'), 1)
        self.assertIn('NativeScreenPlane', kinds)
        wrong = deepcopy(entry)
        wrong['visuals'][1]['placement']['overscan'] = [1.2, 1.2]
        with self.assertRaisesRegex(ValueError, 'match its reconstruction profile'):
            presentation.apply(plan, wrong, sounds, 7)

    def test_lookup_checks_actual_prepared_scale_and_rejects_second_viewport_transform(self):
        snapshot = {'root': 'GL/ability/1', 'records': [
            {'source': 'GL', 'kind': 'ability', 'id': '1', 'data': {'name': 'fixture'}}]}
        unit = {'id':13500, 'ffbe': {'id': 100}}
        skill = {'conversionSource': snapshot}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundles = root/'presentation'; bundles.mkdir()
            project = root/'assets/screen'; project.mkdir(parents=True)
            spec = project/'spec.json'
            entry = {'sourceKey': snapshot['root'], 'sourceSha256': presentation.source_fingerprint(snapshot),
                     'visuals': [{'anchor': 'screen', 'spec': 'assets/screen', 'placement': placement()}]}
            manifest = bundles/'100.json'
            def write_entry():
                manifest.write_text(json.dumps({'form': '100', 'schema': presentation.VERSION,
                                                'moves': {snapshot['root']: entry}}))
            write_entry()
            original = manifest.read_bytes()
            with patch.object(presentation, 'ROOT', root), patch.object(presentation, 'BUNDLES', bundles), \
                    patch('ffbe_attack_director.materialize', side_effect=lambda entry, settings: entry):
                spec.write_text(json.dumps({'runtimeScale': .8}))
                self.assertEqual(presentation.lookup(unit, skill)['visuals'], entry['visuals'])
                for invalid in (1., 0, True, '.8', float('nan')):
                    spec.write_text(json.dumps({'runtimeScale': invalid}))
                    with self.subTest(scale=invalid), self.assertRaisesRegex(ValueError, 'runtimeScale'):
                        presentation.lookup(unit, skill)
                spec.write_text('{}')
                with self.assertRaisesRegex(ValueError, 'runtimeScale'):
                    presentation.lookup(unit, skill)
                self.assertEqual(manifest.read_bytes(), original)
                entry['visuals'][0]['placement']['runtimeScale'] = 1.
                write_entry()
                self.assertEqual(presentation.lookup(unit, skill)['visuals'], entry['visuals'])
                spec.write_text(json.dumps({'runtimeViewport': {'stretchX': 1, 'center': [0, 0]}}))
                with self.assertRaisesRegex(ValueError, 'viewport transform'):
                    presentation.lookup(unit, skill)
                spec.write_text(json.dumps({'runtimeViewport': {}}))
                self.assertEqual(presentation.lookup(unit, skill)['visuals'], entry['visuals'])

    def test_settings_are_explicit_finite_and_scoped(self):
        good = placement()
        presentation.validate_screen_placement(good)
        cases = []
        for field in good:
            bad = deepcopy(good); del bad[field]; cases.append(bad)
        for field, values in {
            'sourceOffset': [[1, 0], [False, 0], [0, float('nan')]],
            'referenceStage': [[0, 320], [320, 8193], [320], '320', [True, 320]],
            'runtimeScale': [0, -.8, 101, float('inf'), True, '.8'],
            'overscan': [[.99, 1.06], [1.06, 2.01], [1.06, False]],
            'cameraDepth': [{'front': 0, 'rearMargin': 300}, {'front': 1000},
                            {'front': 1000, 'rearMargin': float('nan')},
                            {'front': True, 'rearMargin': 300},
                            {'front': 1000, 'rearMargin': 300, 'rear': 3500}],
            'hideNonParticipants': [True], 'camera': [{}], 'hostTargetType': ['Single'],
        }.items():
            cases.extend({**deepcopy(good), field: value} for value in values)
        for bad in cases:
            with self.subTest(placement=bad), self.assertRaises(ValueError):
                presentation.validate_screen_placement(bad)
        self.assertEqual(good, placement())

    def test_updates_start_during_hidden_setup_and_stop_before_destroy(self):
        plan, entry, sounds = fixture()
        result = presentation.apply(plan, entry, sounds, 7)
        updates = [e for e in result['events'] if e['set']['EventType'] == 'NativeScreenPlane']
        self.assertTrue(updates, 'Camera planes must be attached before their first visible frame')
        for i, visual in enumerate(entry['visuals'][:2]):
            aid = 'FFBE_7_' + str(i)
            start = 12000 + visual['frame'] * 400 - 800
            end = start + visual['frames'] * 400
            selected = [e for e in updates if e['set']['NativeScreenPlane_Id'] == aid]
            self.assertEqual([e['time'] for e in selected], list(range(start + 2, end, 800)))
            self.assertLess(selected[0]['time'], start + 800)
            self.assertEqual(selected[0]['set'], {
                'EventType': 'NativeScreenPlane', 'NativeScreenPlane_Id': aid,
                'NativeScreenPlane_SourceWidth': 320., 'NativeScreenPlane_SourceHeight': 320.,
                'NativeScreenPlane_RuntimeScale': .8, 'NativeScreenPlane_OverscanX': 1.06,
                'NativeScreenPlane_OverscanY': 1.06, 'NativeScreenPlane_FrontDepth': 1000.,
                'NativeScreenPlane_RearMargin': 300., 'NativeScreenPlane_IsRear': i == 0})
            self.assertEqual(next(e['time'] for e in result['events'] if
                                 e['set'].get('SsActor_Destroy_ID') == aid), end)
        self.assertFalse(any(e['set']['NativeScreenPlane_Id'] == 'FFBE_7_2' for e in updates))

    def test_source_events_audio_and_caster_are_unchanged(self):
        plan, entry, sounds = fixture()
        before = deepcopy((plan, entry, sounds))
        baseline_entry = deepcopy(entry)
        for visual in baseline_entry['visuals'][:2]:
            visual['placement'] = {'mode': 'frozen_caster_plane', 'sourceOffset': [0, 0]}
        baseline = presentation.apply(plan, baseline_entry, sounds, 7)
        result = presentation.apply(plan, entry, sounds, 7)
        self.assertEqual((plan, entry, sounds), before)
        original_behavior = {**result, 'events': [e for e in result['events']
                                                if e['set']['EventType'] != 'NativeScreenPlane']}
        self.assertEqual(original_behavior, baseline)
        self.assertEqual(next(e['time'] for e in result['events']
                              if e['set']['EventType'] == 'SoundPlayHitSound'), 48000)
        forbidden = ('NativeStage', 'BG', 'OtherChangeSubSpace')
        self.assertFalse(any(e['set']['EventType'].startswith(forbidden) for e in result['events']))

    def test_non_camera_profiles_do_not_receive_camera_plane_updates(self):
        plan, entry, sounds = fixture()
        for visual in entry['visuals'][:2]:
            visual['placement'] = {'mode': 'frozen_caster_plane', 'sourceOffset': [0, 0]}
        result = presentation.apply(plan, entry, sounds, 7)
        self.assertFalse(any(e['set']['EventType'] == 'NativeScreenPlane' for e in result['events']))

    def test_calibrated_target_stage_keeps_its_existing_native_camera(self):
        from tools.tests.test_ffbe_target_stage import fixture as stage_fixture
        plan, entry = stage_fixture()
        entry['_hostVisionUnitId'] = 13503
        profile = entry['reconstructionProfile']['screenPlacement']
        profile['targetRegistration'] = {'partName': 'NULL_Center', 'sourceImpact': [-177, -20]}
        for visual in entry['visuals']:
            if visual['anchor'] == 'screen': visual['placement'] = deepcopy(profile)
        result = presentation.apply(plan, entry, [], 7)
        self.assertTrue(any(e['set']['EventType'] == 'NativeStageCamera' for e in result['events']))
        self.assertFalse(any(e['set']['EventType'] == 'NativeScreenPlane' for e in result['events']))

    def test_plane_parameters_preserve_projection_when_rear_depth_changes(self):
        # Independent pinhole projection oracle for the emitted parameter contract.
        # C++ applies the live camera FOV/aspect, source pixel size and SS6 root scale.
        plan, entry, sounds = fixture()
        result = presentation.apply(plan, entry, sounds, 7)
        fields = next(e['set'] for e in result['events'] if e['set']['EventType'] == 'NativeScreenPlane')
        get = lambda key: fields['NativeScreenPlane_' + key]
        for aspect in (4/3, 16/9, 21/9):
            for fov in (35, 70, 110):
                for depth in (get('FrontDepth'), 3500, 6500):
                    half_width = depth * math.tan(math.radians(fov) / 2)
                    scale_x = 2 * half_width * get('OverscanX') / (get('SourceWidth') * get('RuntimeScale'))
                    scale_y = 2 * half_width / aspect * get('OverscanY') / (get('SourceHeight') * get('RuntimeScale'))
                    ndc_x = get('SourceWidth') / 2 * scale_x * get('RuntimeScale') / half_width
                    ndc_y = get('SourceHeight') / 2 * scale_y * get('RuntimeScale') / (half_width / aspect)
                    self.assertAlmostEqual(ndc_x, 1.06)
                    self.assertAlmostEqual(ndc_y, 1.06)

    def test_rear_margin_is_beyond_rotated_camera_box_support(self):
        plan, entry, sounds = fixture()
        result = presentation.apply(plan, entry, sounds, 7)
        fields = next(e['set'] for e in result['events'] if e['set']['EventType'] == 'NativeScreenPlane')
        margin = fields['NativeScreenPlane_RearMargin']
        camera = (-300, 20, 900)
        forward = (2/3, -1/3, -2/3)
        actors = [((2000, 100, 200), (30, 70, 240)), ((1800, 600, 300), (150, 200, 900))]
        support = max(sum((o-c)*f + abs(f)*e for o,c,f,e in zip(origin,camera,forward,extent))
                      for origin, extent in actors)
        depth = support + margin
        for origin, extent in actors:
            for mask in range(8):
                corner = [o + e * (1 if mask & (1 << i) else -1)
                          for i, (o,e) in enumerate(zip(origin,extent))]
                camera_z = sum((p-c)*f for p,c,f in zip(corner,camera,forward))
                self.assertGreaterEqual(depth - camera_z + 1e-9, margin)


if __name__ == '__main__':
    unittest.main()
