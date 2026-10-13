"""Regression checks for native Bishamon curve semantics and RGBA export."""
import struct
import sys
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import ibmb
import render
import to_ss6


class NativeCurves(unittest.TestCase):
    def test_mixed_native_interpolation_channels(self):
        # Native Curve<3>::ValueN dispatches independently per channel:
        # 0 holds, 1 is linear, 2/3 evaluate the stored Hermite tangents.
        curve = ibmb.Curve(3, 0, [(0., [0., 0., 0.], [0, 1, 2]),
                                 (1., [8., 8., 8.], [0, 1, 2])],
                           [([0., 0., 8.], [0., 0., 0.]),
                            ([0., 0., 0.], [0., 0., -4.])])
        self.assertEqual([0., 2., 2.5625], curve.sample(.25))
        self.assertEqual([8., 8., 8.], curve.sample(1.))
        self.assertEqual([0., 0., 0.], curve.sample(-1.))

    def test_hermite_tangents_use_segment_units(self):
        # The native sampler normalizes time, but does not multiply the
        # tangents by segment duration. Short segments must keep their shape.
        for mode in (2, 3):
            curve = ibmb.Curve(1, 0, [(0., [0.], [1]), (.2, [0.], [mode]),
                                     (.4, [8.], [mode]), (1., [8.], [1])],
                               [([0.], [0.]), ([8.], [0.]),
                                ([0.], [-4.]), ([0.], [0.])])
            self.assertAlmostEqual(2.5625, curve.sample(.25)[0])

    def test_reader_retains_both_tangent_arrays(self):
        header = bytearray(128)
        struct.pack_into('<I', header, ibmb.HDR_POOL, 128)
        struct.pack_into('<I', header, ibmb.HDR_POOL_USED, 40)
        struct.pack_into('<8I', header, ibmb.HDR_RESTABLE, *([0xffffffff] * 8))
        payload = struct.pack('<I4fI4f', 2, 8., 0., 0., 0., 2, 0., -4., 8., 1.)
        curve = ibmb._Reader(bytes(header) + payload).read_curve(0, 2, 1)
        self.assertEqual([([8.], [0.]), ([0.], [-4.])], curve.tangents)
        self.assertAlmostEqual(2.5625, curve.sample(.25)[0])


class NativeGeneration(unittest.TestCase):
    def node(self, index=0, **settings):
        return ibmb.Chunk(index, 0, ibmb.T_NODE, 704, **settings)

    def test_regular_count_window_step_and_burst_gap(self):
        node = self.node(delay=3, emit_count=2, emit_stream=5,
                         emit_step=2., emit_bursts=2, emit_interval=4)
        instances = ibmb._regular_instances([node], 100)
        self.assertEqual([3., 3., 5., 5., 7., 7., 12., 12., 14., 14., 16., 16.],
                         [i[0] for i in instances])

    def test_fractional_emission_is_not_rounded_to_frames(self):
        node = self.node(emit_count=2, emit_stream=2, emit_step=.5)
        self.assertEqual([0., 0., .5, .5, 1., 1., 1.5, 1.5],
                         [i[0] for i in ibmb._regular_instances([node], 100)])

    def test_child_generates_for_every_parent_instance(self):
        parent = self.node(delay=2, emit_count=2, emit_stream=4, emit_step=2.)
        child = self.node(1, delay=3, emit_stream=2, emit_step=1.)
        instances = ibmb._regular_instances([parent, child], 100)
        self.assertEqual([5., 6., 5., 6., 7., 8., 7., 8.], [i[0] for i in instances])
        self.assertEqual(8, len({tuple(i[2]) for i in instances}))
        self.assertEqual([2., 5.], instances[0][1])

    def test_repeated_node_curves_use_their_own_birth_time(self):
        node = self.node(duration=10, slots={ibmb.SLOT_TRANSLATE:
                         ibmb.Curve(3, 0, [(0., [0., 0., 0.], [1, 1, 1]),
                                          (1., [100., 0., 0.], [1, 1, 1])])})
        old = ibmb._node_transform([node], 7, 60, [0.])[0]
        born_later = ibmb._node_transform([node], 7, 60, [5.])[0]
        self.assertEqual([70., 0., 0.], old)
        self.assertEqual([20., 0., 0.], born_later)


class NativeScaling(unittest.TestCase):
    def curve(self, x=70., y=1.):
        return ibmb.Curve(3, 0, [(0., [x, y, 1.], [1, 1, 1]),
                                  (1., [x, y, 1.], [1, 1, 1])])

    def test_constant_selector_ignores_dormant_curve(self):
        # eff_quick_slash_white: native ConstX uses 0.7; the saved, inactive
        # scale curve reaches70. Reading both caused a100x enlarged slash.
        node = ibmb.Chunk(3, 0, ibmb.T_NODE, 704, node_scale=[.7, 1., 1.],
                          scale_mode=16, slots={ibmb.SLOT_SCALE: self.curve()})
        self.assertEqual([.7, .7], ibmb._node_transform([node], 10, 60)[1])

    def test_uniform_mode_is_selected_not_inferred_from_values(self):
        node = ibmb.Chunk(0, 0, ibmb.T_NODE, 704, node_scale=[40., 1., 0.], scale_mode=2)
        self.assertEqual([40., 1., 0.], ibmb._native_scale(node, 0., 0.))
        node.scale_mode = 16
        self.assertEqual([40., 40., 40.], ibmb._native_scale(node, 0., 0.))

    def test_curve_is_absolute_local_scale_and_keeps_parent_scale(self):
        emitter = ibmb.Chunk(0, 0, 3, 2048, base_scale=[90., 90., 90.],
                             scale_mode=5, slots={ibmb.SLOT_SCALE: self.curve(.5, 1.)})
        self.assertEqual((2., 6.), ibmb._emitter_size(emitter, .5, [2., 3.], False, []))
        emitter.scale_mode = 19
        self.assertEqual((2., 3.), ibmb._emitter_size(emitter, .5, [2., 3.], False, []))

    def test_velocity_and_acceleration_use_particle_age(self):
        node = ibmb.Chunk(0, 0, ibmb.T_NODE, 704, node_scale=[1., 4., 1.],
                          scale_mode=4, scale_velocity=[2., -1., 0.],
                          scale_acceleration=[1., 0., 0.])
        self.assertEqual([11.5, 1., 1.], ibmb._native_scale(node, .01, 3.))
        node.scale_mode = 18
        self.assertEqual([11.5, 11.5, 11.5], ibmb._native_scale(node, .01, 3.))
        node.scale_mode = 15
        self.assertEqual([1., 1., 1.], ibmb._native_scale(node, .99, 100.))


class NativeRotation(unittest.TestCase):
    def test_signed_emitter_rotation_cancels_parent_tilt(self):
        # Flash Step barholy: parent1 is +25X, model10 is -25X. The
        # previous baker omitted emitter rotation and left a false ellipse.
        node = ibmb.Chunk(1, 0, ibmb.T_NODE, 704, rotation_mode=1,
                          rotation_base=[25., 0., 0.])
        emitter = ibmb.Chunk(10, 0, 6, 2048, rotation_mode=1,
                             rotation_base=[-25., 0., 0.])
        _, _, rot, mirror, tilt, _ = ibmb._node_transform([node], 10, 60)
        rot, mirror, tilt = ibmb._accumulate_rotation(
            rot, mirror, tilt, ibmb._native_rotation(emitter, .5, 10.))
        self.assertEqual([0., 0.], tilt)
        self.assertEqual(0., rot)
        self.assertFalse(mirror)

    def test_casting_rotation_uses_frame_age_and_dormant_fields_are_ignored(self):
        emitter = ibmb.Chunk(14, 0, 6, 2048, rotation_mode=2,
                             rotation_base=[0., 0., 0.], rotation_velocity=[0., 0., 2.])
        self.assertEqual([0., 0., 30.], ibmb._native_rotation(emitter, .9, 15.))
        emitter.rotation_mode = 1
        self.assertEqual([0., 0., 0.], ibmb._native_rotation(emitter, .9, 15.))
        emitter.rotation_mode = 0
        emitter.rotation_base = [90., 120., 240.]
        self.assertEqual([0., 0., 0.], ibmb._native_rotation(emitter, .9, 15.))

    def test_direct_rotation_curve_is_signed_and_replaces_base(self):
        curve = ibmb.Curve(3, 0, [(0., [-30., 0., 0.], [1, 1, 1]),
                                  (1., [30., 60., -120.], [1, 1, 1])])
        node = ibmb.Chunk(0, 0, ibmb.T_NODE, 704, rotation_mode=4,
                          rotation_base=[90., 90., 90.], slots={ibmb.SLOT_ROTATE: curve})
        self.assertEqual([-15., 15., -30.], ibmb._native_rotation(node, .25, 3.))

    def test_additive_rotation_accumulates_angular_velocity_curve(self):
        curve = ibmb.Curve(3, 0, [(0., [0., 0., 0.], [1, 1, 1]),
                                  (1., [0., 0., 4.], [1, 1, 1])])
        node = ibmb.Chunk(0, 0, ibmb.T_NODE, 704, rotation_mode=6,
                          rotation_base=[0., 0., -25.], rotation_velocity=[0., 0., 999.],
                          slots={ibmb.SLOT_ROTATE_VAR: curve})
        # Native InitConst + sum(new-age curveValue * frameDelta).
        self.assertEqual([0., 0., -22.], ibmb._native_rotation(node, .5, 2.))
        self.assertEqual([0., 0., -23.25], ibmb._native_rotation(node, .375, 1.5))
        node.duration = 4
        self.assertEqual(-7., ibmb._node_transform([node], 6, 60)[2])
        node.slots.clear()
        self.assertEqual([0., 0., -25.], ibmb._native_rotation(node, 1., 4.))

    def test_native_emitter_fixture_changes_actual_bake_rotation(self):
        source = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec/sp_20000_activation_01.bmb'
        if not source.is_file():
            self.skipTest('Optional FFBE source fixture is not distributed with tests')
        effect = ibmb.parse(str(source))
        emitter = effect.chunks[14]
        self.assertEqual(2, emitter.rotation_mode)
        self.assertEqual([0., 0., 2.], emitter.rotation_velocity)
        baked = ibmb.bake(effect, max_frames=25)
        rotations = [(frame, part['rot']) for frame, parts in enumerate(baked['frames'])
                     for part in parts if part['emitter'] == 14]
        self.assertGreater(len(rotations), 2)
        self.assertAlmostEqual(2., (rotations[1][1] - rotations[0][1]) /
                               (rotations[1][0] - rotations[0][0]))

    def test_native_barholy_fixture_cancels_projected_mesh_tilt(self):
        source = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec/sp_20151_barholy.bmb'
        if not source.is_file():
            self.skipTest('Optional FFBE source fixture is not distributed with tests')
        effect = ibmb.parse(str(source))
        self.assertEqual([25., 0., 0.], effect.chunks[1].rotation_base)
        self.assertEqual([-25., 0., 0.], effect.chunks[10].rotation_base)
        baked = ibmb.bake(effect, max_frames=30)
        textures = [baked['textures'][part['tex']] for parts in baked['frames']
                    for part in parts if part['emitter'] == 10]
        self.assertTrue(textures)
        import json
        tilts = [json.loads(texture[len('nativeuv:'):])['tilt'] if texture.startswith('nativeuv:')
                 else [float(x) for x in texture.rsplit('|', 2)[1:]] for texture in textures]
        self.assertTrue(all(tilt == [0., 0.] for tilt in tilts))

    def test_single_interior_key_remains_three_dimensional_rotation(self):
        source = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec/lb_340000117_KH_soraNV_front_unit.bmb'
        if not source.is_file():
            self.skipTest('Optional FFBE source fixture is not distributed with tests')
        effect = ibmb.parse(str(source))
        curve = effect.chunks[65].slots[ibmb.SLOT_ROTATE]
        self.assertEqual(3, curve.dim)
        self.assertGreater(curve.keys[0][0], .4)
        self.assertEqual([0., 125., 0.], curve.sample(0.))
        self.assertEqual([0., 125., 0.], curve.sample(1.))


class ParticlePixels(unittest.TestCase):
    def test_export_keeps_interleaved_draw_order(self):
        from PIL import Image
        base = {'tex': 0, 'uv': [0, 0, 4, 4], 'pos': [0, 0],
                'scale': [1, 1], 'alpha': 1, 'rot': 0}
        doc = {'fps': 60, 'textures': ['test'], 'frames': [
            [dict(base, blend='add'), dict(base, blend='mix')],
            [dict(base, blend='mix'), dict(base, blend='add')]]}
        with tempfile.TemporaryDirectory() as folder, patch.object(to_ss6, 'load_texture', return_value=Image.new('RGBA', (4, 4))):
            spec = to_ss6.convert(doc, folder, 'test')
        model = spec['model']['parts'][1:]
        attrs = spec['animations'][0]['parts']
        def at(keys, frame): return [value for time, value in keys if time <= frame][-1]
        for frame, expected in enumerate((['Add', 'Mix'], ['Mix', 'Add'])):
            self.assertEqual(expected, [part['blend'] for part in model
                                       if at(attrs[part['name']]['Hide'], frame) == 0])

    def test_mesh_rgba_does_not_square_alpha(self):
        mesh = {'vertices': [(-1., -1., 0.), (1., -1., 0.), (-1., 1., 0.)],
                'colors': [(1., .5, .25, .5)] * 3,
                'uvs': [(0., 0.), (0., 0.), (0., 0.)],
                'indices': [0, 1, 2], 'bounds': [-1., -1., 0., 1., 1., 0.]}
        tex = np.ones((2, 2, 4), dtype=np.float32)
        tex[..., 3] = .5
        result = ibmb.rasterise_mesh(mesh, tex, size=8)
        visible = result[..., 3] > 0
        self.assertTrue(visible.any())
        np.testing.assert_allclose(result[visible][0], [1., .5, .25, .25])
        # The actual straight-alpha consumer should draw .25 red, not .0625.
        canvas = np.zeros((8, 8, 4), dtype=np.float32)
        render._blit(canvas, result, 4., 4., [1., 1., 1.], 1., 'add')
        self.assertAlmostEqual(.25, float(canvas[..., 0].max()))

    def test_signed_scale_preserves_texture_mirroring(self):
        class Cache:
            index = {'test': 'test.png'}
            def get(self, name): return np.ones((4, 4, 4), dtype=np.float32)
        particle = {'tex': 0, 'emitter': 1, 'scale': [-2., -3.], 'pos': [0., 0.],
                    'rot': 0., 'alpha': 1., 'blend': 'add', 'flipX': True}
        doc = render.build_doc({'textures': ['test'], 'frames': [[particle]]}, Cache(), 1., 1.)
        item = doc['frames'][0][0]
        self.assertFalse(item['flipX'])  # explicit and scale mirrors cancel
        self.assertTrue(item['flipY'])
        self.assertEqual([.5, .75], item['scale'])


if __name__ == '__main__':
    unittest.main()
