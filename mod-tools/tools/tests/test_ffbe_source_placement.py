"""Native placement contracts, including a fixed copy of the actual Sunray rows."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffbe_effects.source_placement import (
    normalize_effect_placement, normalize_skill_placement, resolve_effect_position,
)


class SourcePlacement(unittest.TestCase):
    def test_actual_five_sunray_variants_are_seven_frame_projectiles(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/source_placement_sunray.json').read_bytes())
        self.assertEqual([str(i) for i in range(237607, 237612)], [r['id'] for r in fixture['abilities']])
        for row in fixture['abilities']:
            fields = next(item.split(':') for item in row['effect_frames'].split('&')
                          if item.split(':')[1] == '20100030')
            result = normalize_skill_placement(fields[2:])
            self.assertTrue(result['supported'], result)
            self.assertEqual('move_to_snapshot', result['temporalBinding'])
            self.assertEqual(('caster', 'target'), (result['startRect']['owner'], result['destinationRect']['owner']))
            self.assertEqual(7, result['travelFrames'])
            self.assertAlmostEqual(7 / 60, result['travelSeconds'])
            self.assertEqual('per_target', result['instances'])
            self.assertNotIn('camera', result)
        effects = [normalize_effect_placement(p) for p in fixture['group']['effect_frames'].split(',')]
        self.assertTrue(all(p['supported'] for p in effects))
        self.assertEqual([28, 34, 40, 46, 52, 58, 64, 70], [p['sourceFrame'] for p in effects])
        self.assertEqual([[0, 0], [40, -40], [-40, 0], [0, 30], [30, -40], [-40, 0], [-30, 40], [0, -30]],
                         [p['offset'] for p in effects])
        self.assertEqual({'99999999'}, {p['reverseEffectId'] for p in effects})
        self.assertFalse(any('loop' in p for p in effects))

    def test_fixed_caster_and_stored_caster_are_distinct_snapshots(self):
        current = normalize_skill_placement(['1', '3', '0'])
        stored = normalize_skill_placement(['1', '7', '0'])
        self.assertEqual('logical_position', current['startRect']['mode'])
        self.assertEqual('stored_touch_rect', stored['startRect']['mode'])
        self.assertEqual(['snapshot', 'snapshot'], [p['temporalBinding'] for p in (current, stored)])
        self.assertFalse(current['startRect']['getEffectDispRectArgument'])
        self.assertTrue(stored['startRect']['getEffectDispRectArgument'])

    def test_reciprocal_projectiles_preserve_rectangle_choice_and_explicit_zero(self):
        current = normalize_skill_placement('1:6:0')
        stored = normalize_skill_placement('1:9:7')
        forward_stored = normalize_skill_placement('1:8:7')
        self.assertEqual('target', current['startRect']['owner'])
        self.assertEqual('caster', current['destinationRect']['owner'])
        self.assertEqual(0, current['travelSeconds'])
        self.assertFalse(current['travelDefaulted'])
        self.assertFalse(current['destinationRect']['getEffectDispRectArgument'])
        self.assertTrue(stored['destinationRect']['getEffectDispRectArgument'])
        self.assertTrue(forward_stored['startRect']['getEffectDispRectArgument'])
        self.assertEqual([0.5, 0.5], stored['destinationPivot'])

    def test_only_proven_native_optional_defaults_are_used(self):
        self.assertTrue(normalize_skill_placement('1')['anchorDefaulted'])
        for raw in ('1:5', '1:5:'):
            parsed = normalize_skill_placement(raw)
            self.assertEqual(1, parsed['travelSeconds'])
            self.assertTrue(parsed['travelDefaulted'])
        self.assertTrue(normalize_skill_placement(['1', '3', 'unused_text'])['supported'])
        self.assertFalse(normalize_skill_placement(['1', '5', None])['supported'])

    def test_screen_uses_field_size_and_zero_origin_and_target_field_keeps_half_rect(self):
        screen = normalize_skill_placement('2:4:0')
        target_field = normalize_skill_placement('1:2:0')
        self.assertEqual([0, 0], screen['startRect']['origin'])
        self.assertEqual('BattleManager.getFieldRect.size', screen['startRect']['size'])
        self.assertEqual('field_half_rectangle', target_field['startRect']['kind'])
        self.assertEqual('target_side', target_field['startRect']['owner'])
        self.assertEqual((2, 50), (screen['layer']['gameLayer'], screen['layer']['zOrderBase']))

    def test_non_square_source_rectangle_has_independent_width_height_and_offsets(self):
        # The native source field has +Y down; converting to host coordinates
        # belongs to its adapter. This asymmetric fixture catches Y/X swaps.
        parsed = normalize_effect_placement('28:1001902:99999999:1:6:4:40:-40')
        self.assertEqual([860, -30], resolve_effect_position(parsed, [20, 10, 800, 300]))
        self.assertEqual([780, -30], resolve_effect_position(parsed, [20, 10, 800, 300], reverse=True))

    def test_native_jitter_is_not_silently_zeroed_or_added_to_stable_axes(self):
        parsed = normalize_effect_placement('28:1001902:99999999:1:2:5:0:0')
        with self.assertRaisesRegex(ValueError, 'samples'):
            resolve_effect_position(parsed, [20, 10, 800, 300])
        self.assertEqual([417, 160], resolve_effect_position(parsed, [20, 10, 800, 300], jitter=(-3, 7)))
        for samples in ((0, 9), (0.2, 0), (False, 0)):
            with self.assertRaises(ValueError):
                resolve_effect_position(parsed, [20, 10, 800, 300], jitter=samples)

    def test_reverse_offsets_are_independent_and_do_not_relabel_reverse_id_as_loop(self):
        parsed = normalize_effect_placement('28:1001902:123:1:5:5:40:-40:none:12')
        self.assertEqual([380, 172], resolve_effect_position(parsed, [20, 10, 800, 300], reverse=True))
        self.assertEqual('123', parsed['reverseEffectId'])
        self.assertEqual('type_10_flips_primary_other_existing_id_replaces_primary', parsed['reverseEffectRule'])

    def test_unknown_and_malformed_fields_are_auditable_and_never_fall_back(self):
        for raw in ([], ['1', '10', '0'], ['9', '3', '0'], ['1', '5', 'nan'],
                    ['1', '5', '-1'], ['1', '5', 'infinity'], ['1', '5', '7', 'extra'],
                    ['1', False, '0'], ['1', '5', '1e309'], ['1', '2147483648', '0']):
            original = deepcopy(raw)
            parsed = normalize_skill_placement(raw)
            self.assertFalse(parsed['supported'], raw)
            self.assertTrue(parsed['issues'])
            self.assertEqual(original, parsed['rawFlags'])
            self.assertEqual(original, raw)
        for raw in ('0:1:2:1:0:2:3:4', '0:1:2:1:2:7:3:4', '0:1:2:1:2:2:bad:4'):
            parsed = normalize_effect_placement(raw)
            self.assertFalse(parsed['supported'])
            self.assertEqual(raw, parsed['rawFields'])
            with self.assertRaises(ValueError):
                resolve_effect_position(parsed, [0, 0, 100, 100])

    def test_input_and_result_raw_lists_do_not_share_mutable_storage(self):
        raw = ['1', '5', '7']
        parsed = normalize_skill_placement(raw)
        parsed['rawFlags'][0] = '2'
        self.assertEqual(['1', '5', '7'], raw)


if __name__ == '__main__':
    unittest.main()
