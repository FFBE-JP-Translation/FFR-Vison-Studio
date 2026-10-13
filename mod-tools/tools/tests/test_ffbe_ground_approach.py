"""One ground-preserving native approach, only when the source already moves."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffbe_presentation as presentation
import ffbe_resonance as resonance


def fixture(moving=True):
    plan = resonance.schedule(2, 2, 7, {'moveType': 1 if moving else 4, 'hitFrames': [30, 90]},
        movement={'target_offset': [12., 34., 56.]})
    entry = {'_hostResonance': True, '_hostVisionUnitId': 9999, 'visuals': [],
        'reconstructionProfile': {'resonanceMovement': {'mode': 'ground_approach'}}}
    return plan, entry


class GroundApproach(unittest.TestCase):
    def test_preserves_existing_horizontal_approach_and_source_clock(self):
        plan, entry = fixture(); before = deepcopy((plan, entry))
        out = presentation.apply(plan, entry, [], 7)
        original = next(e for e in plan['events'] if e['set']['EventType'] == 'UnitMoveToTarget')
        move = next(e for e in out['events'] if e['set']['EventType'] == 'NativeGroundApproach')
        self.assertEqual(move, {'time': original['time'], 'set': {'EventType': 'NativeGroundApproach',
            'NativeGroundApproach_UnitId': 9999, 'NativeGroundApproach_Frame': 12,
            'NativeGroundApproach_PartName': 'Null_root', 'NativeGroundApproach_Offset': {'x': 12., 'y': 34., 'z': 0.}}})
        self.assertEqual([e for e in plan['events'] if e is not original], [e for e in out['events'] if e is not move])
        self.assertEqual((plan, entry), before)
        self.assertEqual(plan['duration'], out['duration'])

    def test_stationary_sources_stay_stationary(self):
        plan, entry = fixture(False)
        self.assertEqual(presentation.apply(plan, entry, [], 7), plan)

    def test_ordinary_or_bespoke_profiles_cannot_use_resonance_grounding(self):
        plan, entry = fixture()
        for change in ({'_hostResonance': False}, {'_hostVisionUnitId': 0}):
            with self.assertRaises(ValueError): presentation.apply(plan, {**entry, **change}, [], 7)
        entry['reconstructionProfile']['casterPlacement'] = 'approach_target'
        with self.assertRaisesRegex(ValueError, 'bespoke'): presentation.apply(plan, entry, [], 7)

    def test_camera_and_grounding_are_independent_and_preserve_return(self):
        plan, entry = fixture()
        entry['reconstructionProfile']['resonanceCamera'] = {'mode': 'participants', 'panFrames': 12, 'restoreFrames': 10}
        out = presentation.apply(plan, entry, [], 7)
        kinds = [e['set']['EventType'] for e in out['events']]
        self.assertEqual(kinds.count('NativeGroundApproach'), 1)
        self.assertGreater(kinds.count('NativeParticipantCamera'), 1)
        self.assertEqual([e for e in plan['events'] if e['set']['EventType'] == 'UnitMoveToDefaultLocation'],
                         [e for e in out['events'] if e['set']['EventType'] == 'UnitMoveToDefaultLocation'])
        self.assertFalse(any(kind.startswith('BG') for kind in kinds))


if __name__ == '__main__': unittest.main()
