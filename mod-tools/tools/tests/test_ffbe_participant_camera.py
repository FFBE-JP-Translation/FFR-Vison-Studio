"""A shared, background-independent Resonance camera with finite native reset."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffbe_presentation as presentation
import ffbe_resonance as resonance
from tools.tests.test_ffbe_camera_plane import placement


def fixture():
    plan = resonance.schedule(2, 2, 7, {'hitFrames': [30, 90]})
    entry = {'_hostResonance': True, '_hostVisionUnitId': 9999, 'visuals': [],
        'reconstructionProfile': {'resonanceCamera': {'mode': 'participants', 'panFrames': 12, 'restoreFrames': 10}}}
    return plan, entry


class ParticipantCamera(unittest.TestCase):
    def test_screenless_resonance_tracks_caster_then_frames_targets_without_source_retiming(self):
        plan, entry = fixture(); before = deepcopy((plan, entry))
        out = presentation.apply(plan, entry, [], 7)
        pans = [e for e in out['events'] if e['set']['EventType'] == 'NativeParticipantCamera']
        self.assertGreater(len(pans), 1)
        self.assertEqual(pans[-1]['set']['NativeParticipantCamera_Shot'], 'targets')
        self.assertTrue(all(e['set']['NativeParticipantCamera_Shot'] == 'caster' for e in pans[:-1]))
        self.assertTrue(all(1 <= e['set']['NativeParticipantCamera_Frame'] <= 4 for e in pans[:-1]))
        self.assertTrue(all(e['set']['NativeParticipantCamera_UnitId'] == 9999 for e in pans))
        for first, second in zip(pans, pans[1:]):
            self.assertLessEqual(first['time'] + first['set']['NativeParticipantCamera_Frame'] * 800, second['time'])
        self.assertEqual(pans[-1]['set']['NativeParticipantCamera_CenterX'], .35)
        self.assertEqual(pans[-1]['set']['NativeParticipantCamera_CenterY'], .56)
        self.assertFalse(any(e['set']['EventType'].startswith('BG') or e['set']['EventType'] in
            ('CameraSetZoomInOut', 'NativeStageCamera', 'UnitMoveToTarget') for e in out['events']))
        self.assertEqual([e for e in plan['events'] if e['set']['EventType'] != 'CameraSetDefault'],
                         [e for e in out['events'] if e['set']['EventType'] not in ('CameraSetDefault', 'NativeParticipantCamera', 'NativeResonanceVisibility')])
        self.assertEqual((plan, entry), before)

    def test_background_and_long_visual_tail_use_same_camera_and_complete_restore(self):
        plan, entry = fixture()
        plane = {**placement(), 'backdrop': 'native_subspace'}
        entry['reconstructionProfile']['screenPlacement'] = plane
        entry['visuals'] = [{'name': 'background', 'asset': '/Game/bg', 'anchor': 'screen',
            'placement': deepcopy(plane), 'layer': 2, 'frame': 0, 'frames': 480}]
        sounds = [{'frame': 90, 'bank': 'source', 'cueName': 'last', 'durationMs': 100}]
        out = presentation.apply(plan, entry, sounds, 7)
        kinds = [e['set']['EventType'] for e in out['events']]
        self.assertIn('BGChange', kinds); self.assertIn('BGRevert', kinds); self.assertIn('NativeScreenPlane', kinds)
        self.assertGreater(kinds.count('NativeParticipantCamera'), 1)
        destroyed = max(e['time'] for e in out['events'] if e['set']['EventType'] == 'SsActorDestroyToSsID')
        resets = [e for e in out['events'] if e['set']['EventType'] == 'CameraSetDefault' and e['time'] > presentation.action_start(out)]
        self.assertEqual(len(resets), 1); self.assertGreater(resets[0]['time'], destroyed)
        self.assertTrue(resets[0]['set']['Camera_SetDefault_IsZoomInOut'])
        self.assertGreater(out['duration'], resets[0]['time'] + 10*800)
        self.assertEqual([e['time']-presentation.action_start(out) for e in out['events']
                          if e['set']['EventType'] == 'SoundPlayHitSound'], [90*400])

    def test_ordinary_commands_and_malformed_profiles_cannot_enable_camera(self):
        plan, entry = fixture()
        for change in ({'_hostResonance': False}, {'_hostVisionUnitId': 0}, {'_hostVisionUnitId': True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                presentation.apply(plan, {**entry, **change}, [], 7)
        for value in (None, True, 0, 121, 12.0, '12'):
            bad = deepcopy(entry); bad['reconstructionProfile']['resonanceCamera']['panFrames'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): presentation.apply(plan, bad, [], 7)
        bad = deepcopy(entry); bad['reconstructionProfile']['resonanceCamera']['offset'] = [0, 200]
        with self.assertRaises(ValueError): presentation.apply(plan, bad, [], 7)

    def test_conflicting_bespoke_camera_is_rejected(self):
        from tools.tests.test_ffbe_target_stage import fixture as bespoke
        plan, entry = bespoke(); entry['_hostVisionUnitId'] = 9999
        entry['reconstructionProfile']['resonanceCamera'] = fixture()[1]['reconstructionProfile']['resonanceCamera']
        with self.assertRaisesRegex(ValueError, 'bespoke'): presentation.apply(plan, entry, [], 7)

    def test_independent_readback_rejects_wrong_actor_missing_restore_and_truncation(self):
        from tools.tests.test_ffbe_target_stage import verify
        plan, entry = fixture(); out = presentation.apply(plan, entry, [], 7)
        self.assertTrue(verify(entry, out)['participantCameraVerified'])
        cases = []
        bad = deepcopy(out)
        next(e for e in bad['events'] if e['set']['EventType'] == 'NativeParticipantCamera')['set']['NativeParticipantCamera_UnitId'] = 1
        cases.append(bad)
        bad = deepcopy(out)
        next(e for e in bad['events'] if e['set']['EventType'] == 'NativeParticipantCamera')['set']['NativeParticipantCamera_CenterX'] = .1
        cases.append(bad)
        bad = deepcopy(out)
        next(e for e in bad['events'] if e['set']['EventType'] == 'NativeResonanceVisibility')['set']['NativeResonanceVisibility_UnitId'] = 1
        cases.append(bad)
        bad = deepcopy(out); bad['events'] = [e for e in bad['events'] if not
            (e['set']['EventType'] == 'NativeResonanceVisibility' and e['set']['NativeResonanceVisibility_Restore'])]
        cases.append(bad)
        bad = deepcopy(out); bad['events'] = [e for e in bad['events'] if not
            (e['set']['EventType'] == 'CameraSetDefault' and e['time'] > presentation.action_start(out))]
        cases.append(bad)
        bad = deepcopy(out); reset = next(e for e in out['events'] if
            e['set']['EventType'] == 'CameraSetDefault' and e['time'] > presentation.action_start(out))
        bad['duration'] = reset['time'] + 10*800
        cases.append(bad)
        for bad in cases:
            with self.assertRaises(AssertionError): verify(entry, bad)

    def test_irregular_first_hit_never_overlaps_a_caster_blend(self):
        from tools.tests.test_ffbe_target_stage import verify
        for first_hit in (1, 29, 30, 63, 85, 107):
            plan, entry = fixture()
            plan = resonance.schedule(2, 2, 7, {'hitFrames': [first_hit, first_hit + 60]})
            out = presentation.apply(plan, entry, [], 7)
            self.assertTrue(verify(entry, out)['participantCameraVerified'])


if __name__ == '__main__': unittest.main()
