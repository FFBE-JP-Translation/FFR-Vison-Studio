"""Native UV motion controls; independently clocked primary/secondary textures."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import ibmb


def module(mode=0, base=None, velocity=None, acceleration=None, slot=6):
    return {'mode': mode, 'base': base or [0., 0., 0.], 'variance': [0., 0., 0.],
            'velocity': velocity or [0., 0., 0.], 'velocityVariance': [0., 0., 0.],
            'acceleration': acceleration or [0., 0., 0.], 'accelerationVariance': [0., 0., 0.],
            'curveSlot': slot}


def emitter():
    c = ibmb.Chunk(0, 0, 2, 2128, life=4)
    c.uv_channels = [{'pivot': [.5, .5, .5], 'translation': module(),
                      'rotation': module(slot=8), 'scaling': module(slot=10)}]
    return c


class NativeUvMotion(unittest.TestCase):
    def fixture(self, suffix):
        p = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec' / (
            'lb_100032707_FFBE_NV_rainking_and_3rdfina_' + suffix + '.bmb')
        if not p.exists(): self.skipTest('local source fixture unavailable')
        return ibmb.parse(str(p))

    def test_velocity_acceleration_are_frame_based_and_signed(self):
        c = emitter()
        c.uv_channels[0]['translation'] = module(3, [1., 2., 3.], [.2, -.4, 0.], [.1, 0., 0.])
        c.uv_channels[0]['rotation'] = module(2, [0., 0., -25.], [0., 0., .02], slot=8)
        c.uv_channels[0]['scaling'] = module(1, [-.5, 2., 1.], slot=10)
        v = ibmb._native_uv_channel(c, 0, 10.)
        self.assertEqual([8., -2., 3.], v['translation'])
        self.assertAlmostEqual(-24.8, v['rotation'][2])
        self.assertEqual([-.5, 2., 1.], v['scaling'])

    def test_selector_ignores_dormant_curve_and_payload(self):
        c = emitter()
        c.uv_channels[0]['translation'] = module(1, [.2, .3, 0.], [999., 999., 999.])
        c.slots[6] = ibmb.Curve(3, 0, [(0., [999., 999., 999.], [1, 1, 1])])
        self.assertEqual([.2, .3, 0.], ibmb._native_uv_channel(c, 0, 3)['translation'])
        c.uv_channels[0]['translation']['mode'] = 0
        self.assertEqual([0., 0., 0.], ibmb._native_uv_channel(c, 0, 3)['translation'])
        self.assertEqual([1., 1., 1.], ibmb._native_uv_channel(c, 0, 3)['scaling'])

    def test_add_curve_integrates_and_clamps_life_domain_without_rescaling_history(self):
        c = emitter()
        c.uv_channels[0]['translation'] = module(6, [10., 0., 0.], [999., 0., 0.])
        c.slots[7] = ibmb.Curve(3, 0, [(0., [0., 0., 0.], [1, 1, 1]),
                                     (1., [4., 0., 0.], [1, 1, 1])])
        # Per-frame native update samples 1+2+3+4+4+4, then adds base10.
        self.assertEqual([28., 0., 0.], ibmb._native_uv_channel(c, 0, 6)['translation'])
        # Fractional birth phase: .5 * sample(.5) + sample(1.5).
        self.assertEqual([11.75, 0., 0.], ibmb._native_uv_channel(c, 0, 1.5)['translation'])

    def test_random_curve_unsupported_is_explicit(self):
        c = emitter()
        c.uv_channels[0]['rotation']['mode'] = 5
        result = ibmb._native_uv_channel(c, 0, 2)
        self.assertEqual([{'module': 'rotation', 'mode': 5}], result['unsupported'])

    def test_nebula_partial_curve_and_degree_rotation(self):
        c = self.fixture('back_center').chunks[4]
        self.assertEqual('space_006_h_002', c.res1)
        self.assertEqual([4, 2, 1], [c.uv_channels[0][n]['mode'] for n in ('translation', 'rotation', 'scaling')])
        self.assertEqual(3, c.slots[6].dim)
        self.assertGreater(c.slots[6].keys[0][0], 0.)
        self.assertLess(c.slots[6].keys[-1][0], .32)
        a, b = [ibmb._native_uv_channel(c, 0, age) for age in (0., 309.)]
        self.assertAlmostEqual(-.203086376, a['translation'][1])
        self.assertAlmostEqual(.067289323, b['translation'][0])
        self.assertAlmostEqual(6.18, b['rotation'][2], places=5)
        self.assertEqual([.5, .5, .5], b['scaling'])
        self.assertEqual([], b['unsupported'])

    def test_vertical_and_diagonal_streaks_scroll_with_independent_mask_rotation(self):
        for suffix, ids in [('back_center', (7, 8, 9, 11, 12, 13)),
                            ('front_center', (4, 5, 6, 8, 9, 10))]:
            eff = self.fixture(suffix)
            for index in ids:
                c = eff.chunks[index]
                self.assertEqual(('tornado_001', 'beam_009'), (c.res1, c.res2))
                a = ibmb._native_uv_channel(c, 0, 0.)
                b = ibmb._native_uv_channel(c, 0, 4.)
                expected = .8 if index in ((7, 11) if suffix == 'back_center' else (4, 8)) else .3
                self.assertAlmostEqual(expected, b['translation'][0] - a['translation'][0], places=6)
                self.assertEqual([0., 0., 90.], ibmb._native_uv_channel(c, 1, 4.)['rotation'])

    def test_model_primary_scroll_and_quad_secondary_scroll(self):
        eff = self.fixture('front_unit')
        for index, expected in ((49, .4), (55, .2)):
            c = eff.chunks[index]
            self.assertAlmostEqual(expected, ibmb._native_uv_channel(c, 0, 10.)['translation'][1], places=6)
            self.assertEqual([0., 0., 0.], ibmb._native_uv_channel(c, 1, 10.)['translation'])
        c = eff.chunks[58]
        self.assertEqual('distortion_003', c.res2)
        self.assertAlmostEqual(.5, ibmb._native_uv_channel(c, 1, 5.)['translation'][0], places=6)

    def test_fixed_variance_uses_component_and_channel_identity(self):
        class FixedVariation:
            def __init__(self): self.names = []
            def sample(self, name, base, spread):
                self.names.append(name)
                return [a - b for a, b in zip(base, spread)]
        c = self.fixture('back_center').chunks[4]
        variation = FixedVariation()
        a = ibmb._native_uv_channel(c, 0, 0., variation=variation)
        b = ibmb._native_uv_channel(c, 0, 100., variation=variation)
        self.assertEqual(-360., a['rotation'][2])
        self.assertAlmostEqual(2., b['rotation'][2] - a['rotation'][2], places=6)
        self.assertIn('uv1_rotation_base', variation.names)
        self.assertNotIn('uv1_translation_base', variation.names)

    def test_shader_material_ignores_dormant_secondary_and_preserves_native_wrap(self):
        eff = self.fixture('back_center')
        nebula = ibmb._native_texture_material(eff.chunks[4], .5)
        self.assertEqual(0, nebula['mode'])
        self.assertNotIn('secondary', nebula)
        self.assertEqual([1., 1., 1., 1.], nebula['colorScale1'])
        self.assertEqual([], nebula['unsupported'])
        streak = ibmb._native_texture_material(eff.chunks[7], .5)
        self.assertEqual((1, 'beam_009'), (streak['mode'], streak['secondary']))
        self.assertEqual([2, 1], streak['wrap'])
        self.assertEqual([1, 1], streak['filter'])

    def test_model_secondary_texture_and_distortion_channel_color_curve(self):
        eff = self.fixture('front_unit')
        globe = ibmb._native_texture_material(eff.chunks[49], .7)
        self.assertEqual('tex_flame_001b', globe['primary'])
        self.assertEqual('tex_flame_003', globe['secondary'])
        self.assertEqual(2, globe['mode'])
        self.assertAlmostEqual(.205673754, globe['colorScale2'][0])
        wave = eff.chunks[58]
        material = ibmb._native_texture_material(wave, .7)
        self.assertEqual((6, 'distortion_003'), (material['mode'], material['secondary']))
        self.assertEqual(3, wave.slots[23].dim)
        self.assertEqual(wave.slots[23].sample(.7), material['colorScale1'][:3])
        self.assertEqual([128/255.] * 3, material['distortionMid'])
        self.assertEqual([], material['unsupported'])

    def test_texture_alpha_uses_independent_constant_curve_selectors(self):
        c = self.fixture('front_unit').chunks[55]
        c.texture_material['alpha'][0] = {'mode': 1, 'base': -.2, 'variance': 0.}
        c.texture_alpha_curves[0] = ibmb.Curve(1, 0, [(.2, [.3], [1]), (.6, [.8], [1])])
        self.assertEqual(0., ibmb._native_texture_material(c, .9)['colorScale1'][3])
        c.texture_material['alpha'][0]['mode'] = 2
        self.assertEqual(.8, ibmb._native_texture_material(c, .9)['colorScale1'][3])
        c.texture_material['alpha'][0]['mode'] = 0
        self.assertEqual(1., ibmb._native_texture_material(c, .9)['colorScale1'][3])

    def test_model_particle_global_alpha_selector_is_separate_from_texture_alpha(self):
        eff = self.fixture('front_unit')
        # Model55 is globally faded by Curve3 while its primary texture alpha
        # module is None0. Model85 selects RandomCurve4, not the default curve.
        self.assertEqual(3, eff.chunks[55].quad_alpha_mode)
        self.assertEqual(0, eff.chunks[55].texture_material['alpha'][0]['mode'])
        self.assertEqual(4, eff.chunks[85].quad_alpha_mode)
        for suffix in ('front_center', 'front_unit'):
            for c in self.fixture(suffix).emitters():
                if c.type == 3 and c.enabled:
                    self.assertEqual(3, c.quad_alpha_mode)
                    self.assertIsNotNone(c.alpha_curve)
                    self.assertEqual(3, c.to_dict()['globalAlphaMode'])


if __name__ == '__main__': unittest.main()
