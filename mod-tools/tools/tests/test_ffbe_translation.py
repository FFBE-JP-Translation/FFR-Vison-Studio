"""Native translation selectors and Rain & Fina source regression checks."""
from pathlib import Path
import math
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import ibmb


class NativeTranslation(unittest.TestCase):
    def chunk(self, mode, **values):
        return ibmb.Chunk(0, 0, ibmb.T_NODE, 704, translation_mode=mode, **values)

    def curve(self, a=(0., 0., 0.), b=(4., 8., -4.)):
        return ibmb.Curve(3, 0, [(0., list(a), [1, 1, 1]), (1., list(b), [1, 1, 1])])

    def test_constant_and_zero_modes_ignore_dormant_curves(self):
        node = self.chunk(2, translation_base=[-122., 18., -4.],
                          slots={0: self.curve((900., 900., 900.), (999., 999., 999.))})
        self.assertEqual([-122., 18., -4.], ibmb._native_translation(node, .5, 12.))
        for mode in (0, 1):
            node.translation_mode = mode
            self.assertEqual([0., 0., 0.], ibmb._native_translation(node, .5, 12.))

    def test_velocity_and_acceleration_keep_signed_xyz_frame_units(self):
        node = self.chunk(4, translation_base=[25., 0., 2.],
                          translation_velocity=[3., -8., -1.],
                          translation_acceleration=[.2, 0., 0.])
        self.assertEqual([65., -80., -8.], ibmb._native_translation(node, .9, 10.))
        node.translation_mode = 3
        self.assertEqual([55., -80., -8.], ibmb._native_translation(node, .9, 10.))

    def test_position_curves_replace_base_and_additive_curves_integrate_slot_one(self):
        for mode in (5, 6):
            node = self.chunk(mode, translation_base=[333., 333., 333.],
                              slots={0: self.curve()})
            self.assertEqual([2., 4., -2.], ibmb._native_translation(node, .5, 2.))
        for mode in (7, 8):
            node = self.chunk(mode, translation_base=[10., 0., 0.],
                              translation_velocity=[999., 999., 999.],
                              slots={0: self.curve((999.,)*3, (999.,)*3), 1: self.curve()})
            self.assertEqual([13., 6., -3.], ibmb._native_translation(node, .5, 2.))
            self.assertEqual([11.75, 3.5, -1.75], ibmb._native_translation(node, .375, 1.5))

    def test_additive_curve_keeps_clock_after_parent_duration_and_cache_is_exact(self):
        node = self.chunk(7, duration=4, slots={1: self.curve()})
        cache = {}
        for age in (2., 6., 1.5, 3.5, 6.):
            self.assertEqual(ibmb._native_translation(node, age / 4., age),
                             ibmb._native_translation(node, age / 4., age, cache))
        self.assertEqual([18., 36., -18.], ibmb._node_transform([node], 6, 60)[0])

    def test_parent_transform_applies_to_child_displacement_not_ancestor_origin(self):
        parent = self.chunk(2, translation_base=[177., 10., 0.],
                            rotation_mode=1, rotation_base=[0., 180., 0.],
                            scale_mode=2, node_scale=[2., 3., 1.])
        child = self.chunk(2, translation_base=[5., 2., 0.])
        position = ibmb._node_transform([parent, child], 0, 60)[0]
        for expected, actual in zip([167., 16., 0.], position):
            self.assertAlmostEqual(expected, actual)
        self.assertEqual([177., 10., 0.], ibmb._node_transform([parent], 0, 60)[0])

    def test_point_frames_keep_noncommuting_parent_child_rotations(self):
        parent = self.chunk(1, rotation_mode=1, rotation_base=[0., 0., 90.])
        child = self.chunk(1, rotation_mode=1, rotation_base=[90., 0., 0.])
        grandchild = self.chunk(2, translation_base=[0., 1., 0.])
        # Child X rotation sends +Y to +Z; parent Z rotation keeps it there.
        position = ibmb._node_transform([parent, child, grandchild], 0, 60)[0]
        for expected, actual in zip([0., 0., 1.], position):
            self.assertAlmostEqual(expected, actual)

    def test_rain_fina_bake_keeps_opposing_sweep_origins(self):
        effect = self.source('front_center')
        baked = ibmb.bake(effect, max_frames=effect.duration)
        # Parent2 rotates both origins -52 degrees. Average the four UV
        # mirror tiles to recover each emitter's center from the actual bake.
        for emitter, origin_x in ((4, -122.), (8, 177.)):
            tiles = next([part['pos'] for part in parts if part['emitter'] == emitter]
                         for parts in baked['frames']
                         if any(part['emitter'] == emitter for part in parts))
            center = [sum(point[i] for point in tiles) / len(tiles) for i in range(2)]
            self.assertAlmostEqual(origin_x * math.cos(math.radians(-52.)), center[0], places=3)
            self.assertAlmostEqual(origin_x * math.sin(math.radians(-52.)), center[1], places=3)

    def source(self, suffix):
        path = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec' / (
            'lb_100032707_FFBE_NV_rainking_and_3rdfina_' + suffix + '.bmb')
        if not path.is_file():
            self.skipTest('Optional local FFBE source fixture is not distributed')
        return ibmb.parse(str(path))

    def test_rain_fina_sweeps_and_accelerating_fire_read_exact_source_fields(self):
        back = self.source('back_center')
        self.assertEqual(2, back.chunks[6].translation_mode)
        self.assertEqual([-122., 0., 0.], back.chunks[6].translation_base)
        self.assertEqual([88., 0., 0.], back.chunks[10].translation_base)
        front = self.source('front_center')
        self.assertEqual([177., 0., 0.], front.chunks[7].translation_base)
        self.assertEqual(3, front.chunks[14].translation_mode)
        self.assertEqual([2., 0., 0.], front.chunks[14].translation_velocity)
        unit = self.source('front_unit')
        flame = unit.chunks[23]
        self.assertEqual(4, flame.translation_mode)
        self.assertEqual([3., -8., -1.], flame.translation_velocity)
        self.assertAlmostEqual(.2, flame.translation_acceleration[0])
        self.assertAlmostEqual(65., ibmb._native_translation(flame, .5, 10.)[0], places=6)


if __name__ == '__main__':
    unittest.main()
