"""Universal prepared offsets replace legacy ad-hoc spacing exactly once."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import make_vision_mod as generator
import ffbe_presentation as presentation
import ffbe_resonance as resonance


def fixture():
    return {'_hostResonance': True, '_hostVisionUnitId': 13503, 'visuals': [],
        'sourcePlacement': {'hostAdapter': 'logical_rectangle_to_root_v1'},
        'reconstructionProfile': {'resonanceMovement': {'mode': 'ground_approach'},
                                  'export': {'scaleMult': 1., 'runtimeScale': .8}},
        'sourceMovement': {'version': 1, 'sourceOffset': [40., 3.], 'sourceEndpointX': 101.5,
            'casterWidthContribution': 29.5,
            'targetProxy': {'animationSize': [64, 128], 'effectSize': [64, 128], 'attackOffset': [0, 0]},
            'ffrTargetOffset': [-8.4, 284.2, 0.], 'unitsPerSourcePixel': 2.8,
            'preserveElevation': True, 'useNativeSpacing': False,
            'policy': 'source_approach_with_target_proxy'}}


class PreparedGroundMovement(unittest.TestCase):
    def test_prepared_scale_and_proxy_do_not_receive_old_right_shift(self):
        entry = fixture(); original = deepcopy(entry)
        settings = generator.resonance_movement_settings({}, entry)
        self.assertEqual(settings, {'target_offset': [-8.4, 284.2, 0.], 'right_shift': 0.})
        source = {'moveType': 1, 'hitFrames': [30], 'movement': {'ffrTargetOffset': [-3, 40, 0]}}
        plan = resonance.schedule(2, 1, 7, source, [], settings)
        plan = presentation.apply(plan, entry, [], 7)
        move = next(e['set'] for e in plan['events'] if e['set']['EventType'] == 'NativeGroundApproach')
        self.assertEqual(move['NativeGroundApproach_Offset'], {'x': -8.4, 'y': 284.2, 'z': 0.})
        self.assertEqual(entry, original)

    def test_explicit_user_changes_override_prepared_spacing(self):
        entry = fixture(); skill = {'movement': {'target_offset': [1, 2, 0], 'right_shift': 9, 'enabled': False}}
        before = deepcopy((skill, entry))
        self.assertEqual(generator.resonance_movement_settings(skill, entry), skill['movement'])
        self.assertEqual((skill, entry), before)
        self.assertEqual(generator.resonance_movement_settings({'movement': {'right_shift': 10}}, entry),
                         {'target_offset': [-8.4, 284.2, 0.], 'right_shift': 10})

    def test_legacy_and_stationary_behaviors_are_not_reinterpreted(self):
        entry = fixture(); del entry['sourcePlacement']
        self.assertIsNone(generator.resonance_movement_settings({}, entry))
        self.assertEqual(generator.resonance_movement_settings({'movement': {'right_shift': 12}}, entry), {'right_shift': 12})
        entry = fixture(); entry['reconstructionProfile'].pop('resonanceMovement')
        self.assertIsNone(generator.resonance_movement_settings({}, entry))
        self.assertEqual(generator.resonance_movement_settings({}, fixture(), fallback=True), {'enabled': False})
        settings = generator.resonance_movement_settings({}, fixture())
        plan = resonance.schedule(2, 1, 7, {'moveType': 4, 'hitFrames': [30]}, [], settings)
        self.assertFalse(any(e['set']['EventType'] == 'UnitMoveToTarget' for e in plan['events']))

    def test_inconsistent_scale_mapping_or_clearance_fails_before_build(self):
        changes = [('version', True), ('useNativeSpacing', True), ('preserveElevation', False),
                   ('sourceEndpointX', 102), ('unitsPerSourcePixel', 1.), ('unitsPerSourcePixel', float('nan')),
                   ('ffrTargetOffset', [-8.4, 484.2, 0]), ('ffrTargetOffset', [-8.4, 284.2, 56]),
                   ('sourceOffset', [True, 3]), ('policy', 'source_offset_with_native_clearance')]
        for field, value in changes:
            entry = fixture(); entry['sourceMovement'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'Prepared ground movement'):
                generator.resonance_movement_settings({}, entry)
        entry = fixture(); entry['reconstructionProfile']['export']['runtimeScale'] = 1.
        with self.assertRaises(ValueError): generator.resonance_movement_settings({}, entry)
        entry = fixture(); del entry['sourceMovement']
        with self.assertRaises(ValueError): generator.resonance_movement_settings({}, entry)


if __name__ == '__main__': unittest.main()
