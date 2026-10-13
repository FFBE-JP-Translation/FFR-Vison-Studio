"""Native resource-free particles use vertex RGBA without texture sampling."""
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


class UntexturedParticles(unittest.TestCase):
    def test_constant_vertex_color_ignores_texture_tint_and_dormant_curve(self):
        emitter = ibmb.Chunk(0, 0, 3, 1840, particle_color_mode=1,
                            particle_color_base=[0., .2, .4], color=[1., 1., 1., 1.])
        emitter.slots[19] = ibmb.Curve(3, 0, [(0., [1., 1., 1.], [1, 1, 1])])
        self.assertEqual([0., .2, .4], ibmb._native_particle_color(emitter, .5))
        emitter.particle_color_mode = 3
        self.assertEqual([1., 1., 1.], ibmb._native_particle_color(emitter, .5))
        emitter.particle_color_mode = 99
        with self.assertRaisesRegex(ValueError, 'Unsupported untextured'):
            ibmb._native_particle_color(emitter, .5)

    def test_source_fades_have_black_rgb_independent_of_alpha_ramps(self):
        directory = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec'
        for amount in (50, 75):
            source = directory / f'eff_fadeblack_a{amount}_f90.bmb'
            if not source.exists(): self.skipTest('local source fixture unavailable')
            effect = ibmb.parse(str(source))
            emitter = effect.emitters()[0]
            self.assertEqual([], effect.textures)
            self.assertEqual(1, emitter.particle_color_mode)
            self.assertEqual([0., 0., 0.], emitter.particle_color_base)
            self.assertEqual([1., 1., 1.], emitter.color[:3])
            baked = ibmb.bake(effect, max_frames=90, canonical_variation=True)
            self.assertEqual(['solid:white'], baked['textures'])
            self.assertEqual([], baked['frames'][0])
            for frame, alpha in ((15, amount / 100), (45, amount / 100),
                                 (75, amount / 100), (85, amount / 100 * 7 / 27)):
                part = baked['frames'][frame][0]
                self.assertEqual([0., 0., 0.], part['color'])
                self.assertAlmostEqual(alpha, part['alpha'], places=3)
                self.assertEqual('normal', part['blend'])
            self.assertEqual([550., 450.], baked['frames'][45][0]['scale'])

    def test_neutral_cell_preserves_vertex_rgba_and_authored_geometry(self):
        with tempfile.TemporaryDirectory() as td, patch.object(render, 'MESH_SPRITE_DIR', td):
            Image.new('RGBA', (2, 2), (0, 0, 0, 255)).save(Path(td) / 'native_solid_white.png')
            cache = render.TextureCache([])
            np.testing.assert_array_equal(cache.get('solid:white'), np.ones((2, 2, 4)))
            baked = {'textures': ['solid:white'], 'frames': [[
                {'tex': 0, 'pos': [4., 125.], 'scale': [550., 450.], 'rot': 12.,
                 'alpha': .75, 'color': [.1, .2, .3], 'blend': 'mix'}]]}
            doc = render.build_doc(baked, cache, 1., 1.)
            part = doc['frames'][0][0]
            self.assertEqual([4., 125.], part['pos'])
            self.assertEqual([275., 225.], part['scale'])
            self.assertEqual([.1, .2, .3], part['color'])
            self.assertEqual(.75, part['alpha'])
            self.assertEqual(12., part['rot'])
            self.assertEqual(set(), cache.missing)
            image = np.asarray(Image.open(Path(td) / doc['textures'][0]))
            self.assertTrue(np.all(image == 255))

    def test_curve_changes_with_time_under_fixed_instance_variation(self):
        emitter = ibmb.Chunk(0, 0, 3, 1840, particle_color_mode=3,
                            particle_color_variance=[.01, .01, .01])
        emitter.slots[19] = ibmb.Curve(3, 0, [(0., [.2, .3, .4], [1, 1, 1]),
                                           (1., [.6, .7, .8], [1, 1, 1])])
        variation = ibmb._CanonicalVariation(12345, 'fixture').instance((('emitter', 0),))
        early = ibmb._native_particle_color(emitter, 0., variation)
        late = ibmb._native_particle_color(emitter, 1., variation)
        np.testing.assert_allclose(np.asarray(late) - early, [.4, .4, .4])
        emitter.particle_color_mode = 2
        with self.assertRaisesRegex(ValueError, 'synchronized color variance'):
            ibmb._native_particle_color(emitter, .5, variation)


if __name__ == '__main__':
    unittest.main()
