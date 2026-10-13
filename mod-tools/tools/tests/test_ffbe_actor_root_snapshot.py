"""Frozen source geometry samples the actual group dispatch, without new offsets."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffbe_presentation as presentation


def fixture(anchor='caster'):
    plan = {'duration': 80000, 'events': [
        {'time': 12000, 'set': {'EventType': 'UnitPlayAnimByName', 'Unit_PlayAnimByName_AnimationName': 'LB1'}},
        {'time': 60000, 'set': {'EventType': 'OtherReaction'}}]}
    fx = {'name': 'source', 'asset': '/Game/source', 'anchor': anchor, 'partName': 'root',
          'frame': 29, 'frames': 80, 'layer': 1, 'sourceCoordinates': {
              'binding': 'actor_root_snapshot', 'sampleFrame': 29,
              'rectangleMode': 'animation1_static', 'owner': 'caster' if anchor == 'caster' else 'target',
              'offsetsApplied': True}}
    return plan, {'visuals': [fx], '_hostVisionUnitId': 7777}


class ActorRootSnapshot(unittest.TestCase):
    def test_dispatch_snapshot_skips_only_blank_lead_frames(self):
        for anchor in ('caster', 'each_target', 'target_group'):
            plan, entry = fixture(anchor); original = deepcopy((plan, entry))
            out = presentation.apply(plan, entry, [], 7)
            kinds = lambda k: [e for e in out['events'] if e['set']['EventType'] == k]
            spawn = kinds('SsActorSpawnSpriteStudioActor')[0]
            self.assertEqual(spawn['time'], 12000+29*400)
            fields = spawn['set']['SsActor_SsData']
            self.assertTrue(fields['bDisableFollowing']); self.assertEqual(fields['PartName'], 'root')
            self.assertEqual(fields['bSpawnRelativeTarget'], anchor != 'caster')
            self.assertEqual(fields['addLocation'], {'x': -8., 'y': 0., 'z': 0.})
            self.assertFalse(kinds('SsActorMoveToTargetToSsID'))
            play = kinds('SsActorPlayAnimToSsID')[0]
            root = kinds('NativeActorRootSnapshot')[0]
            self.assertEqual(root, {'time': spawn['time']+1, 'set': {'EventType': 'NativeActorRootSnapshot',
                'NativeActorRootSnapshot_Id': 'FFBE_7_0', 'NativeActorRootSnapshot_UnitId': 7777,
                'NativeActorRootSnapshot_IsTarget': anchor != 'caster', 'NativeActorRootSnapshot_Depth': -8.}})
            self.assertEqual(play['time'], spawn['time']+2)
            self.assertEqual(play['set']['SsActor_PlayAnim_StartFrame'], 2)
            self.assertEqual(kinds('SsActorDestroyToSsID')[0]['time'], spawn['time']+78*400)
            self.assertEqual((plan, entry), original)

    def test_legacy_effect_without_snapshot_marker_retains_old_spawn(self):
        plan, entry = fixture(); del entry['visuals'][0]['sourceCoordinates']
        out = presentation.apply(plan, entry, [], 7)
        spawn = next(e for e in out['events'] if e['set']['EventType'] == 'SsActorSpawnSpriteStudioActor')
        self.assertEqual(spawn['time'], 12000+29*400-800)
        self.assertFalse(spawn['set']['SsActor_SsData']['bDisableFollowing'])

    def test_mismatched_snapshot_evidence_is_rejected(self):
        plan, entry = fixture()
        for field, value in [('binding', 'animated_center'), ('offsetsApplied', False), ('sampleFrame', 30), ('owner', 'target')]:
            bad = deepcopy(entry); bad['visuals'][0]['sourceCoordinates'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): presentation.apply(plan, bad, [], 7)

    def test_missing_selected_host_vision_and_missing_native_binding_are_rejected(self):
        from tools.tests.test_ffbe_target_stage import verify
        plan, entry = fixture(); del entry['_hostVisionUnitId']
        with self.assertRaisesRegex(ValueError, 'selected host vision'): presentation.apply(plan, entry, [], 7)
        plan, entry = fixture(); out = presentation.apply(plan, entry, [], 7)
        self.assertEqual(verify(entry, out)['actorRootSnapshotsVerified'], 1)
        out['events'] = [e for e in out['events'] if e['set']['EventType'] != 'NativeActorRootSnapshot']
        with self.assertRaisesRegex(AssertionError, 'root binding'): verify(entry, out)


if __name__ == '__main__': unittest.main()
