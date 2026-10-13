"""Native Quad color4 channels and valid partial alpha curves."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import ibmb
import render


class QuadColors(unittest.TestCase):
    def test_constant_selector_ignores_stale_curve(self):
        em = ibmb.Chunk(0, 0, 2, 2128, quad_color_mode=1,
                        quad_colors=[[.1, .2, 1.], [1., 0., 0.], [1., 0., 0.], [1., 0., 0.]])
        em.slots[19] = ibmb.Curve(3, 0, [(0., [1., 0., 0.], [1, 1, 1])])
        self.assertEqual([[.1, .2, 1.]] * 4, ibmb._native_quad_colors(em, .6))

    def test_curve_selector_replaces_authored_constant(self):
        em = ibmb.Chunk(0, 0, 2, 2128, quad_color_mode=3, quad_colors=[[0., 0., 0.]] * 4)
        em.slots[19] = ibmb.Curve(3, 0, [(0., [1., .3, .1], [1, 1, 1]),
                                       (.5, [.2, .4, 1.], [1, 1, 1])])
        self.assertEqual([[.2, .4, 1.]] * 4, ibmb._native_quad_colors(em, .9))

    def test_border_colors_are_rgb_and_alpha_curve_ends_early(self):
        p = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec/lb_rarity_NV_frame_effect_240F_orange.bmb'
        if not p.exists(): self.skipTest('local source fixture unavailable')
        eff = ibmb.parse(str(p))
        for em in eff.emitters():
            self.assertEqual(20, em.quad_color_mode)
            colors = ibmb._native_quad_colors(em, .5)
            self.assertEqual([0., 0., 0.], colors[0])
            np.testing.assert_allclose([1., 172/255, 103/255], colors[1], atol=1e-6)
            self.assertEqual(colors[1], colors[2])
            self.assertEqual(colors[0], colors[3])
            self.assertEqual(3, em.quad_alpha_mode)
            self.assertIsNotNone(em.alpha_curve)
            self.assertLess(em.alpha_curve.keys[-1][0], 1.)
            self.assertEqual(0., em.alpha_curve.sample(1.)[0])

    def test_baked_gradient_preserves_world_size_and_independent_alpha(self):
        with tempfile.TemporaryDirectory() as td, patch.object(render, 'MESH_SPRITE_DIR', td):
            Image.new('RGBA', (2, 2), (255, 255, 255, 128)).save(Path(td) / 'white.png')
            colors = [[0., 0., 0.], [1., .675, .404], [1., .675, .404], [0., 0., 0.]]
            baked = {'textures': ['white'], 'frames': [[{'tex': 0, 'pos': [0., 0.],
                      'scale': [380., 60.], 'rot': 0., 'alpha': .5, 'blend': 'add',
                      'vertexColors': colors}]]}
            cache = render.TextureCache([td])
            doc = render.build_doc(baked, cache, 1., 1.)
            part = doc['frames'][0][0]
            image = np.asarray(Image.open(Path(td) / doc['textures'][part['tex']]))
            self.assertEqual(.5, part['alpha'])
            self.assertTrue(np.all(image[..., 3] == 128))
            self.assertLess(image[0, 32, 0], 3)
            np.testing.assert_allclose(image[-1, 32, :3], [253, 170, 102], atol=2)
            self.assertAlmostEqual(380., part['scale'][0] * image.shape[1], places=3)
            self.assertAlmostEqual(60., part['scale'][1] * image.shape[0], places=3)

    def test_native_destination_darken_exports_black_with_source_alpha(self):
        p = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec/lb_100032707_FFBE_NV_rainking_and_3rdfina_front_unit.bmb'
        if not p.exists(): self.skipTest('local source fixture unavailable')
        eff = ibmb.parse(str(p))
        # This authored white plate is a destination-darkening pass. Treating
        # the alpha selector as its blend enum previously made it flash white.
        self.assertEqual(3, eff.chunks[48].blend)
        baked = ibmb.bake(eff, max_frames=100, max_particles=256)
        samples = [p for frame in baked['frames'] for p in frame if p['emitter'] == 48]
        self.assertTrue(samples)
        for p in samples:
            self.assertEqual('mix', p['blend'])
            self.assertEqual([0., 0., 0.], p['color'])
            self.assertGreater(p['alpha'], 0.)

    def test_final_flash_retains_authored_emitter_delay(self):
        p = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec/lb_100032707_FFBE_NV_rainking_and_3rdfina_front_unit.bmb'
        if not p.exists(): self.skipTest('local source fixture unavailable')
        eff = ibmb.parse(str(p))
        flash = eff.chunks[80]
        self.assertEqual(188, flash.emitter_delay)
        self.assertEqual(0, flash.emitter_delay_variance)
        self.assertEqual(44, flash.life)
        self.assertEqual(188, flash.to_dict()['emitterDelay'])


class ModelTextureColor(unittest.TestCase):
    def test_constant_selector_ignores_stale_texture_curve(self):
        em = ibmb.Chunk(0, 0, 6, 1904, texture_color_scale1_mode=1,
                        texture_color_scale1_base=[.2, .4, .8])
        em.slots[20] = ibmb.Curve(3, 0, [(0., [1., 0., 0.], [1, 1, 1])])
        self.assertEqual([.2, .4, .8], ibmb._native_texture_color_scale1(em, .7))
        em.texture_color_scale1_mode = 0
        self.assertEqual([1., 1., 1.], ibmb._native_texture_color_scale1(em, .7))

    def test_authored_globe_rims_change_blue_to_gold_in_baked_output(self):
        p = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec/lb_100032707_FFBE_NV_rainking_and_3rdfina_front_unit.bmb'
        if not p.exists(): self.skipTest('local source fixture unavailable')
        eff = ibmb.parse(str(p))
        baked = ibmb.bake(eff, max_frames=226, max_particles=256)
        for index in (49, 55):
            em = eff.chunks[index]
            self.assertEqual(2, em.texture_color_scale1_mode)
            curve = em.slots[20]
            self.assertEqual(3, curve.dim)
            self.assertGreater(curve.keys[0][0], 0.)
            if index == 49: self.assertLess(curve.keys[-1][0], 1.)
            import json
            def texture_color(frame):
                part = next(p for p in baked['frames'][frame] if p['emitter'] == index)
                self.assertEqual([1., 1., 1.], part['color'])
                return json.loads(baked['textures'][part['tex']][len('nativeuv:'):])['material']['colorScale1'][:3]
            early, late = texture_color(150), texture_color(225)
            self.assertGreater(early[2], early[0])
            self.assertGreater(late[0], late[1])
            self.assertGreater(late[1], late[2])
            expected = curve.sample((225 - 84) / em.life)
            np.testing.assert_allclose(late, expected, atol=.0001)


if __name__ == '__main__': unittest.main()
