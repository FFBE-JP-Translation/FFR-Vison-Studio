"""Source target registration changes host placement, never source art or clocks."""
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_ffbe_target_stage import fixture, bytype, verify
import ffbe_presentation as presentation


def registered_fixture():
    plan, entry = fixture()
    placement = entry['reconstructionProfile']['screenPlacement']
    placement['camera']['focalLength'] = 50
    placement['layerDepth'] = {'back': 64, 'front': -32}
    placement['targetRegistration'] = {'partName': 'NULL_Center', 'sourceImpact': [-177, -20]}
    entry['_hostVisionUnitId'] = 13503
    # Prepared source metadata must survive host registration untouched.
    entry['spawns'] = [{'file': 'source_background.bmb', 'x': -96, 'y': 84,
                        'frame': 0, 'scale': 1, 'groupId': '8008450'}]
    for fx in entry['visuals']:
        fx['spec'] = 'prepared/'+fx['name']
        fx['checksums'] = {'spec.json': 'a'*64, 'tex.bgra': 'b'*64}
        if fx['anchor'] == 'screen': fx['placement'] = deepcopy(placement)
    return plan, entry


def replace_registration(entry, registration):
    placement = entry['reconstructionProfile']['screenPlacement']
    placement['targetRegistration'] = deepcopy(registration)
    for fx in entry['visuals']:
        if fx['anchor'] == 'screen': fx['placement']['targetRegistration'] = deepcopy(registration)


class TargetRegistration(unittest.TestCase):
    def assert_vector(self, actual, expected):
        self.assertEqual(set(actual), set(expected))
        for axis in expected: self.assertAlmostEqual(actual[axis], expected[axis], places=6)

    def test_all_source_layers_register_to_native_enemy_body_center(self):
        plan, entry = registered_fixture()
        out = presentation.apply(plan, entry, [], 7)
        move = bytype(out, 'UnitMoveToTarget')[0][1]
        self.assertEqual(move['Unit_MoveToTarget_PartName'], 'NULL_Center')
        self.assertTrue(move['Unit_MoveToTarget_IsDisableOffset'])
        self.assertTrue(move['Unit_MoveToTarget_IsVisionUnit'])
        self.assert_vector(move['Unit_MoveToTarget_AddLocation'], {'x': 0, 'y': 495.6, 'z': 56})
        for i, fx in enumerate(entry['visuals']):
            aid = f'FFBE_7_{i}'
            depth = -32 if fx['layer'] == 1 else 64
            _, fields = next((t, e) for t, e in bytype(out, 'SsActorMoveToTargetToSsID')
                             if e['SsActor_MoveToTarget_ID'] == aid)
            self.assertEqual(fields['SsActor_MoveToTarget_partName'], 'NULL_Center')
            self.assertEqual(fields['SsActor_MoveToTarget_targetPointID'], -1)
            self.assertFalse(fields['SsActor_MoveToTarget_RelativeActionUnit'])
            self.assert_vector(fields['SsActor_MoveToTarget_plusOffset'], {'x': depth, 'y': 495.6, 'z': 56})
        self.assertTrue(verify(entry, out)['targetStageVerified'])

    def test_camera_uses_positioned_vision_root_without_double_target_offset(self):
        plan, entry = registered_fixture()
        out = presentation.apply(plan, entry, [], 7)
        first = min(t for t, _ in bytype(out, 'SsActorSpawnSpriteStudioActor'))
        camera = bytype(out, 'NativeStageCamera')
        self.assertEqual(len(camera), 1)
        self.assertEqual(camera[0][0], first-3)
        self.assertEqual(camera[0][1]['NativeStageCamera_UnitId'], 13503)
        self.assert_vector(camera[0][1]['NativeStageCamera_AddLocation'], {'x': 0, 'y': -268.8, 'z': 235.2})
        self.assertFalse(bytype(out, 'CameraSetLookAtTarget'))
        lens = bytype(out, 'CameraSetZoomInOut')
        self.assertEqual(lens[0][0], first-2)
        self.assertEqual(lens[0][1]['Camera_SetZoomInOut_Value'], 50)
        self.assertFalse(lens[0][1]['Camera_SetZoomInOut_RelativeValue'])
        # A previous target-specific approach offset cannot shift this camera
        # or affect the source impact-to-body registration.
        other = deepcopy(plan)
        bytype(other, 'UnitMoveToTarget')[0][1]['Unit_MoveToTarget_AddLocation'] = {'x': -500., 'y': 700., 'z': 123.}
        changed = presentation.apply(other, entry, [], 7)
        self.assertEqual(bytype(out, 'NativeStageCamera'), bytype(changed, 'NativeStageCamera'))
        self.assertEqual(bytype(out, 'UnitMoveToTarget'), bytype(changed, 'UnitMoveToTarget'))

    def test_source_hit_sound_animation_and_effect_clocks_and_art_are_invariant(self):
        plan, entry = registered_fixture()
        before = deepcopy((plan, entry))
        sounds = [{'frame': 0, 'bank': 'source_bank', 'cueName': 'cast', 'durationMs': 300},
                  {'frame': 37, 'bank': 'source_bank', 'cueName': 'impact', 'durationMs': 950}]
        ordinary_stage = deepcopy(entry)
        del ordinary_stage['reconstructionProfile']['screenPlacement']['targetRegistration']
        for fx in ordinary_stage['visuals']:
            if fx['anchor'] == 'screen': del fx['placement']['targetRegistration']
        baseline = presentation.apply(plan, ordinary_stage, sounds, 7)
        out = presentation.apply(plan, entry, sounds, 7)
        for kind in ('OtherReaction', 'SoundPlayHitSound', 'UnitPlayAnimByName',
                     'SsActorSpawnSpriteStudioActor', 'SsActorPlayAnimToSsID',
                     'SsActorDestroyToSsID', 'BGRevert', 'CameraSetDefault'):
            with self.subTest(event=kind): self.assertEqual(bytype(baseline, kind), bytype(out, kind))
        self.assertEqual(presentation.action_start(baseline), presentation.action_start(out))
        self.assertEqual(baseline['duration'], out['duration'])
        self.assertEqual(before, (plan, entry))
        self.assertTrue(bytype(out, 'OtherReaction'))
        self.assertEqual(len(bytype(out, 'SoundPlayHitSound')), 2)

    def test_registration_and_camera_share_configured_unit_conversion(self):
        plan, entry = registered_fixture()
        placement = entry['reconstructionProfile']['screenPlacement']
        placement['camera'].update(unitsPerPixel=2, runtimeScale=1.25)
        for fx in entry['visuals']:
            if fx['anchor'] == 'screen': fx['placement'] = deepcopy(placement)
        out = presentation.apply(plan, entry, [], 7)
        self.assert_vector(bytype(out, 'UnitMoveToTarget')[0][1]['Unit_MoveToTarget_AddLocation'],
                           {'x': 0, 'y': 442.5, 'z': 50})
        self.assert_vector(bytype(out, 'NativeStageCamera')[0][1]['NativeStageCamera_AddLocation'],
                           {'x': 0, 'y': -240, 'z': 210})
        self.assertTrue(verify(entry, out)['targetStageVerified'])

    def test_registration_rejects_invalid_part_coordinates_and_overflow(self):
        _, entry = registered_fixture()
        placement = entry['reconstructionProfile']['screenPlacement']
        registrations = [False, [], {}, {'partName': 'Null_root', 'sourceImpact': [-177, -20]},
                         {'partName': '', 'sourceImpact': [-177, -20]}]
        for impact in (None, [], [0], [0, 1, 2], [True, 0], ['-177', -20],
                       [math.nan, 0], [0, math.inf], [1e308, 0]):
            registrations.append({'partName': 'NULL_Center', 'sourceImpact': impact})
        for registration in registrations:
            with self.subTest(registration=registration), self.assertRaises(ValueError):
                presentation.validate_screen_placement({**placement, 'targetRegistration': registration})

    def test_missing_host_vision_and_mismatched_screen_registration_fail(self):
        plan, entry = registered_fixture()
        for host in (None, False, 0, -1, '13503', 13503.5):
            bad = deepcopy(entry)
            if host is None: bad.pop('_hostVisionUnitId')
            else: bad['_hostVisionUnitId'] = host
            with self.subTest(host=host), self.assertRaises(ValueError): presentation.apply(plan, bad, [], 7)
        for registration in (None, {'partName': 'NULL_Center', 'sourceImpact': [-178, -20]}):
            bad = deepcopy(entry)
            if registration is None: bad['visuals'][0]['placement'].pop('targetRegistration')
            else: bad['visuals'][0]['placement']['targetRegistration'] = registration
            with self.subTest(registration=registration), self.assertRaises(ValueError):
                presentation.apply(plan, bad, [], 7)

    def test_readback_rejects_mutually_matching_but_stale_target_root_placement(self):
        plan, entry = registered_fixture(); good = presentation.apply(plan, entry, [], 7)
        self.assertTrue(verify(entry, good)['targetStageVerified'])
        bad = deepcopy(good)
        move = bytype(bad, 'UnitMoveToTarget')[0][1]
        move['Unit_MoveToTarget_PartName'] = 'Null_root'
        move['Unit_MoveToTarget_AddLocation'] = {'x': 12., 'y': 34., 'z': 56.}
        for _, e in bytype(bad, 'SsActorMoveToTargetToSsID'):
            e['SsActor_MoveToTarget_partName'] = 'Null_root'
            e['SsActor_MoveToTarget_plusOffset'] = {'x': e['SsActor_MoveToTarget_plusOffset']['x']+12, 'y': 34., 'z': 56.}
        with self.assertRaises(AssertionError): verify(entry, bad)

    def test_readback_rejects_wrong_vision_camera_offset_missing_or_legacy_camera(self):
        plan, entry = registered_fixture(); good = presentation.apply(plan, entry, [], 7)
        cases = []
        bad = deepcopy(good); bytype(bad, 'NativeStageCamera')[0][1]['NativeStageCamera_UnitId'] = 1001; cases.append(bad)
        bad = deepcopy(good); bytype(bad, 'NativeStageCamera')[0][1]['NativeStageCamera_AddLocation']['y'] += 495.6; cases.append(bad)
        bad = deepcopy(good); bad['events'] = [e for e in bad['events'] if e['set']['EventType'] != 'NativeStageCamera']; cases.append(bad)
        bad = deepcopy(good); bad['events'].append({'time': bytype(good, 'NativeStageCamera')[0][0], 'set': {
            'EventType': 'CameraSetLookAtTarget', 'Camera_SetLookAtTarget_Id': -1}}); cases.append(bad)
        for index, bad in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(AssertionError): verify(entry, bad)

    def test_lookup_injects_selected_vision_for_registration_without_aura_override(self):
        _, entry = registered_fixture()
        snapshot = {'root': 'GL/lb/111', 'records': []}
        entry.update(sourceKey=snapshot['root'], sourceSha256=presentation.source_fingerprint(snapshot), _hostVisionUnitId=99999)
        entry['reconstructionProfile'].update(form='111', sourceKey=snapshot['root'])
        self.assertNotIn('hideNativeAuras', entry['reconstructionProfile']['screenPlacement'])
        bundle = {'schema': presentation.VERSION, 'form': '111', 'moves': {snapshot['root']: entry}}
        with tempfile.TemporaryDirectory() as folder, patch.object(presentation, 'BUNDLES', Path(folder)):
            Path(folder, '111.json').write_text(json.dumps(bundle), encoding='utf-8')
            for host in (13503, 13509):
                selected = presentation.lookup({'ffbe': {'id': 111}, 'id': host}, {'conversionSource': snapshot})
                self.assertEqual(selected['_hostVisionUnitId'], host)
            for host in (None, False, 0, -1, '13503'):
                with self.subTest(host=host), self.assertRaises(ValueError):
                    presentation.lookup({'ffbe': {'id': 111}, 'id': host}, {'conversionSource': snapshot})
            self.assertEqual(json.loads(Path(folder, '111.json').read_text(encoding='utf-8')), bundle)

    def test_absent_registration_preserves_legacy_stage_camera_and_approach(self):
        plan, entry = fixture()
        out = presentation.apply(plan, entry, [], 7)
        self.assertFalse(bytype(out, 'NativeStageCamera'))
        self.assertEqual(len(bytype(out, 'CameraSetLookAtTarget')), 1)
        self.assertEqual(bytype(out, 'UnitMoveToTarget')[0][1]['Unit_MoveToTarget_PartName'], 'Null_root')
        self.assertEqual(bytype(out, 'UnitMoveToTarget')[0][1]['Unit_MoveToTarget_AddLocation'], {'x': 12., 'y': 34., 'z': 56.})
        self.assertTrue(verify(entry, out)['targetStageVerified'])


if __name__ == '__main__': unittest.main()
