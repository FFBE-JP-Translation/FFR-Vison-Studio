"""Recovered source rectangles remain distinct from host sprite animation."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffbe_effects.host_coordinates import (
    HostScale, animation_geometry, binding_group_key, effect_rectangle,
    load_unit_geometry, load_unit_geometry_from_folder, movement_offset, parse_unit_geometry, resolve_snapshot,
    single_target_approach, ground_approach_offset,
    source_rectangle, stored_touch_rectangle,
)
from ffbe_effects.source_placement import normalize_effect_placement, normalize_skill_placement


# Exact GL+JP master inputs; native loader branch addresses are documented in
# build/effects-followup-20260913/unit-movement-inputs.json. No host tuning here.
SORA = {'7KYufEd5': '114:139:49:105', 'LBye01Wi': '120:0,180:0', 'rB70Ls63': '5'}
RAIN_FINA = {'7KYufEd5': '74:50:75:111', 'LBye01Wi': '160:0,40:0', 'rB70Ls63': '5'}


def snapshot(geometry, logical, default=None, reverse=False):
    return {'geometry': geometry, 'logicalPosition': list(logical),
            'storedRectangle': stored_touch_rectangle(geometry, default or logical, reverse=reverse),
            'preserveStoredRect': False}


class UnitGeometry(unittest.TestCase):
    def test_actual_source_normal_and_lb_offsets_are_distinct(self):
        for row, normal, lb in ((SORA, 120, 180), (RAIN_FINA, 160, 40)):
            geometry = parse_unit_geometry(row, [300, 280])
            self.assertEqual([normal, 0], movement_offset(geometry))
            self.assertEqual([lb, 0], movement_offset(geometry, limit_burst=True))
            self.assertEqual([-lb, 0], movement_offset(geometry, limit_burst=True, reverse=True))
            self.assertEqual(5, geometry['moveSpeed'])

    def test_missing_lb_pair_is_constructor_zero_and_empty_fields_are_native_defaults(self):
        row = dict(SORA, LBye01Wi='120:3')
        self.assertEqual([0, 0], parse_unit_geometry(row, [300, 280])['moveOffsetLb'])
        blank = {'TouchRect': '', 'MoveOffset': '', 'MoveSpeed': '0'}
        geometry = parse_unit_geometry(blank, [64, 80])
        self.assertEqual([0, 0, 0, 0], geometry['touchRect'])
        self.assertEqual([0, 0], geometry['moveOffset'])
        self.assertEqual([68, 20, 64, 80], stored_touch_rectangle(geometry, [100, 100]))

    def test_malformed_master_values_do_not_create_guessed_geometry(self):
        for key, value in [('LBye01Wi', '1'), ('LBye01Wi', '1:2,'),
                           ('LBye01Wi', '1:2,3:4,5:6'), ('7KYufEd5', '1:2:-3:4'),
                           ('rB70Ls63', '256'), ('rB70Ls63', True)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                parse_unit_geometry(dict(SORA, **{key: value}), [300, 280])
        with self.assertRaisesRegex(ValueError, 'Missing'):
            parse_unit_geometry({}, [300, 280])
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            parse_unit_geometry(dict(SORA, TouchRect='0:0:0:0'), [300, 280])

    def test_size_query_uses_all_referenced_unrotated_parts_not_cgs_motion_or_alpha(self):
        with tempfile.TemporaryDirectory() as directory:
            cgg, cgs = Path(directory) / 'unit.csv', Path(directory) / 'animation-1.csv'
            # Frame0 includes an invisible rotated part: native size still counts
            # its unrotated rectangle. Frame2 is huge but is never referenced.
            cgg.write_text('0,2,-10,-20,0,0,100,0,0,0,30,40,0,20,-5,0,0,0,90,0,0,50,10,0,\n'
                           '0,1,-30,10,0,0,100,0,0,0,10,60,0,\n'
                           '0,1,-999,-999,0,0,100,0,0,0,9999,9999,0,\n')
            cgs.write_text('0,700,900,2,\n1,-800,-900,3,\n0,0,0,1,\n')
            result = animation_geometry(cgg, cgs, anime_scale=(2, .5))
            self.assertEqual([-30, -20, 70, 70], result['unscaledBounds'])
            self.assertEqual([200, 45], result['size'])
            self.assertEqual([0, 1], result['referencedGroups'])
            self.assertEqual(3, result['cgsRows'])
            geometry = load_unit_geometry(SORA, cgg, cgs, anime_scale=(2, .5))
            self.assertEqual(result, geometry['provenance']['animationGeometry'])
            self.assertEqual([200, 45], geometry['animationSize'])
            self.assertTrue(all(len(s['sha256']) == 64 for s in result['sources']))

    def test_missing_cgs_group_rejected_instead_of_using_current_sprite(self):
        with tempfile.TemporaryDirectory() as directory:
            cgg, cgs = Path(directory) / 'unit.csv', Path(directory) / 'animation-1.csv'
            cgg.write_text('0,0\n')
            cgs.write_text('1,0,0,1\n')
            with self.assertRaisesRegex(ValueError, 'unavailable'):
                animation_geometry(cgg, cgs)

    def test_generic_folder_fallback_is_explicit_and_strict_mode_remains_available(self):
        with tempfile.TemporaryDirectory() as directory:
            geometry = load_unit_geometry_from_folder(SORA, directory, '1')
            self.assertEqual([163, 244], geometry['animationSize'])
            self.assertEqual('authored_touch_extents_or_64', geometry['provenance']['fallback'])
            self.assertTrue(geometry['approximations'])
            with self.assertRaises(ValueError):
                load_unit_geometry_from_folder(SORA, directory, '1', allow_fallback=False)
            Path(directory, 'unit_cgg_1.csv').write_text('0,1,-2.5,1.25,0,0,100,0,0,0,20.5,30.25,0,\n')
            Path(directory, 'unit_idle_cgs_1.csv').write_text('0,0,0,1,\n')
            geometry = load_unit_geometry_from_folder(SORA, directory, '1')
            self.assertEqual([20.5, 30.25], geometry['animationSize'])
            self.assertEqual('idle', geometry['provenance']['animationName'])

    def test_single_target_approach_accounts_for_source_pivot_and_both_offset_inputs(self):
        geometry = parse_unit_geometry(SORA, [300, 280])
        result = single_target_approach(geometry, target_position=[200, 400],
            target_animation_size=[100, 200], target_effect_size=[80, 160],
            limit_burst=True, target_attack_offset=[10, -4])
        self.assertEqual(456.5, result['x'])  # 200+50+(49/2-8)+180+10
        self.assertEqual([360, 400], result['yRandomArguments'])
        self.assertEqual(-4, result['yAfterRandomOffset'])
        mirrored = single_target_approach(geometry, target_position=[500, 400],
            target_animation_size=[100, 200], target_effect_size=[80, 160],
            target_kind='character', target_left=False, caster_left=True, limit_burst=True)
        self.assertEqual(253.5, mirrored['x'])  # 500-50-(49/2-8)-180

    def test_ground_offset_uses_same_source_scale_without_historical_staging_shift(self):
        geometry = parse_unit_geometry(dict(SORA, LBye01Wi='120:0,180:10'),[300,280])
        result = ground_approach_offset(geometry,limit_burst=True)
        self.assertEqual([180,10],result['sourceOffset'])
        self.assertAlmostEqual(-28,result['ffrTargetOffset'][0])
        self.assertAlmostEqual(639.8,result['ffrTargetOffset'][1])
        self.assertEqual(0,result['ffrTargetOffset'][2])
        self.assertTrue(result['preserveElevation'])
        self.assertFalse(result['useNativeSpacing'])
        self.assertEqual(228.5,result['sourceEndpointX'])
        self.assertEqual('source_approach_with_target_proxy',result['policy'])

    def test_active_and_stored_rectangle_and_reversal_are_separate_native_branches(self):
        geometry = parse_unit_geometry(SORA, [300, 280])
        normal = stored_touch_rectangle(geometry, [500, 400])
        reversed_rect = stored_touch_rectangle(geometry, [500, 400], reverse=True)
        self.assertEqual([464, 259, 49, 105], normal)
        self.assertEqual([487, 259, 49, 105], reversed_rect)
        active = effect_rectangle(geometry, [600, 450], reversed_rect)
        self.assertEqual([564, 309, 49, 105], active)
        self.assertEqual(reversed_rect, effect_rectangle(geometry, [600, 450], reversed_rect, stored=True))
        self.assertEqual(reversed_rect, effect_rectangle(geometry, [600, 450], reversed_rect, preserve_stored=True))

    def test_zero_dimension_fallback_and_mirrored_left_edge(self):
        geometry = parse_unit_geometry(dict(SORA, **{'7KYufEd5': '20:30:0:0'}), [100, 120])
        self.assertEqual([470, 310, 80, 90], stored_touch_rectangle(geometry, [500, 400]))
        self.assertEqual([450, 310, 80, 90], stored_touch_rectangle(geometry, [500, 400], reverse=True))
        bad = parse_unit_geometry(dict(SORA, **{'7KYufEd5': '200:0:0:0'}), [100, 120])
        with self.assertRaisesRegex(ValueError, 'negative'):
            stored_touch_rectangle(bad, [0, 0])


class HostCoordinates(unittest.TestCase):
    def setUp(self):
        self.geometry = parse_unit_geometry(SORA, [300, 280])
        self.caster = snapshot(self.geometry, [600, 450], [500, 400])
        self.target = snapshot(parse_unit_geometry({'TouchRect': '0:0:0:0', 'MoveOffset': '', 'MoveSpeed': '0'}, [100, 200]), [200, 400])
        self.context = dict(caster=self.caster, target=self.target, field_rectangle=[10, 20, 640, 360], target_side='left')

    def test_center_is_not_foot_or_animated_socket_and_offsets_are_applied_once(self):
        skill = normalize_skill_placement('1:3:0')
        effect = normalize_effect_placement('10:1:0:0:5:5:-100:40')
        result = resolve_snapshot(skill, effect, snapshot_frame=0, **self.context)
        # Active caster rect center588.5,361.5; source offset(-100,+40).
        self.assertEqual([488.5, 401.5], result['sourceStart'])
        self.assertEqual([-111.5, -48.5], result['start']['sourcePixels'])
        self.assertAlmostEqual(-312.2, result['start']['worldPlane'][0])
        self.assertAlmostEqual(135.8, result['start']['worldPlane'][1])
        self.assertEqual('actor_root_snapshot', result['binding']['kind'])
        self.assertFalse(result['binding']['followActor'])
        self.assertFalse(result['binding']['animatedSocket'])
        self.assertFalse(result['applied'])
        self.assertNotIn('camera', result)
        before = deepcopy(result)
        self.caster['logicalPosition'][0] = 999
        self.assertEqual(before, result)

    def test_scale_chain_cancels_document_scale_and_reverses_y_once(self):
        result = HostScale().vector([100, 40])
        self.assertEqual([240, -96], result['documentPixels'])
        self.assertEqual([100, -40], result['ss6Pixels'])
        self.assertEqual([280, -112], result['worldPlane'])
        other = HostScale(document_pixels_per_source=7, export_scale=1.6, runtime_scale=1).vector([100, 40])
        self.assertEqual([160, -64], other['ss6Pixels'])
        self.assertEqual([560, -224], other['worldPlane'])
        for values in ({'runtime_scale': 0}, {'units_per_pixel': float('nan')}, {'export_scale': True}):
            with self.assertRaises(ValueError):
                HostScale(**values)

    def test_field_half_is_not_target_centroid_and_screen_discards_field_origin(self):
        screen = normalize_skill_placement('1:4')['startRect']
        side = normalize_skill_placement('2:2')['startRect']
        self.assertEqual([0, 0, 640, 360], source_rectangle(screen, **self.context))
        self.assertEqual([10, 20, 320, 360], source_rectangle(side, **self.context))
        self.assertEqual([330, 20, 320, 360], source_rectangle(side, **dict(self.context, target_side='right')))
        with self.assertRaisesRegex(ValueError, 'explicit'):
            source_rectangle(side, **dict(self.context, target_side=None))
        effect = normalize_effect_placement('0:1:0:0:5:5:0:0')
        result = resolve_snapshot(normalize_skill_placement('1:4'), effect, snapshot_frame=0, **self.context)
        self.assertEqual([.5, .5], result['binding']['sourceUv'])
        self.assertEqual([0, 0], result['start']['worldPlane'])

    def test_projectile_destination_uses_sampled_target_center_and_actual_travel(self):
        effect = normalize_effect_placement('28:1:0:0:2:2:40:-40')
        result = resolve_snapshot(normalize_skill_placement('1:5:7'), effect, snapshot_frame=40,
                                  jitter=[3, -2], **self.context)
        self.assertEqual([631.5, 319.5], result['sourceStart'])
        self.assertEqual([200, 300], result['movement']['destinationSource'])
        self.assertEqual(7, result['movement']['travelFrames'])
        self.assertEqual([-400, -150], result['movement']['destination']['sourcePixels'])
        self.assertEqual('per_target', result['instances'])
        with self.assertRaisesRegex(ValueError, 'jitter'):
            resolve_snapshot(normalize_skill_placement('1:5:7'), effect, snapshot_frame=40, **self.context)

    def test_grouping_does_not_merge_different_snapshot_or_motion_semantics(self):
        placements = [normalize_skill_placement(flags) for flags in ('1:3', '1:7', '2:3', '1:5:7', '1:5:8', '1:8:7')]
        keys = {binding_group_key(p, snapshot_frame=40) for p in placements}
        self.assertEqual(len(placements), len(keys))
        self.assertNotEqual(binding_group_key(placements[0], snapshot_frame=40), binding_group_key(placements[0], snapshot_frame=41))
        self.assertNotEqual(binding_group_key(placements[0], snapshot_frame=40), binding_group_key(placements[0], snapshot_frame=40, phase='cast'))

    def test_unknown_source_and_implicit_unit_state_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            binding_group_key(normalize_skill_placement('1:99'), snapshot_frame=0)
        del self.caster['preserveStoredRect']
        with self.assertRaisesRegex(ValueError, 'explicit'):
            source_rectangle(normalize_skill_placement('1:3')['startRect'], **self.context)


if __name__ == '__main__':
    unittest.main()
