"""Animated texture sampling stays float32 and temporary pixel caches stay bounded."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import render
import to_ss6
import uv_sampling as uv


def state(offset=0.):
    return {'translation': [offset, 0, 0], 'rotation': [0, 0, 0],
            'scaling': [1, 1, 1], 'pivot': [.5, .5, .5]}


def virtual(offset):
    return 'nativeuv:' + json.dumps({'texture': 'source', 'channels': [state(offset)], 'wrap': 1}, sort_keys=True)


class TextureMemory(unittest.TestCase):
    def test_model_without_primary_texture_uses_vertex_color_not_a_missing_png(self):
        with tempfile.TemporaryDirectory() as td, patch.object(render, 'MESH_SPRITE_DIR', td):
            (Path(td) / 'glow.m3r').write_bytes(b'fixture')
            payload = {'texture': 'glow', 'model': 'glow', 'tilt': [25, 0], 'channels': [state()], 'wrap': 1,
                       'material': {'mode': 0, 'primary': None}}
            with patch.object(render.ibmb, 'parse_m3r'), patch.object(render.ibmb, 'rasterise_mesh', side_effect=lambda mesh, tex, *a, **kw: tex):
                cache = render.TextureCache([td])
                arr = cache.get('nativeuv:' + json.dumps(payload))
                self.assertTrue(np.all(arr == 1))
                self.assertNotIn('glow', cache.missing)
                payload['texture'] = 'actually_missing'
                payload['material']['primary'] = 'actually_missing'
                self.assertIsNone(cache.get('nativeuv:' + json.dumps(payload)))

    def test_fully_culled_mesh_has_a_real_transparent_texture_file(self):
        with tempfile.TemporaryDirectory() as td, patch.object(render, 'MESH_SPRITE_DIR', td):
            Image.new('RGBA', (2, 2), 'white').save(Path(td) / 'source.png')
            (Path(td) / 'flat.m3r').write_bytes(b'fixture')
            name = 'nativeuv:' + json.dumps({'texture': 'source', 'model': 'flat', 'tilt': [90, 0],
                'channels': [state()], 'wrap': 1})
            with patch.object(render.ibmb, 'parse_m3r'), patch.object(render.ibmb, 'rasterise_mesh', return_value=None):
                cache = render.TextureCache([td])
                result = cache.get(name)
            self.assertEqual((1, 1, 4), result.shape)
            self.assertFalse(result.any())
            self.assertTrue(Path(cache.index[name.lower()]).is_file())

    def test_all_sample_and_material_modes_keep_single_precision(self):
        texture = np.full((4, 4, 4), .4, dtype=np.float32)
        u, v = uv.grid(4, 4)
        for wrap in (0, 1, 2):
            for filtering in (0, 1):
                sampled = uv.sample(texture, u, v, wrap, filtering)
                self.assertEqual(np.dtype('float32'), sampled.dtype)
                self.assertEqual(4 * 4 * 4 * 4, sampled.nbytes)
        for mode in (0, 1, 2, 6):
            material = {'mode': mode, 'wrap': [1, 1], 'filter': [1, 1],
                        'colorScale1': [1., .8, .7, 1.], 'colorScale2': [.1, .1, .1, .5],
                        'distortionMid': [.5, .5, .5]}
            result = uv.shade(texture, texture, u, v, [state(), state()], material,
                              np.array([.8, .9, 1., 1.], dtype=np.float64))
            self.assertEqual(np.dtype('float32'), result.dtype)

    def test_virtual_lru_preserves_source_pixels_and_evicted_disk_paths(self):
        with tempfile.TemporaryDirectory() as td, patch.object(render, 'MESH_SPRITE_DIR', td):
            source = np.arange(4 * 4 * 4, dtype=np.uint8).reshape(4, 4, 4) * 4
            Image.fromarray(source, 'RGBA').save(Path(td) / 'source.png')
            cache = render.TextureCache([td], virtual_cache_limit=2)
            a, b, c = [virtual(n / 9) for n in range(3)]
            cold = cache.get(a)
            self.assertEqual(np.dtype('float32'), cold.dtype)
            cache.get(b)
            self.assertIs(cold, cache.get(a))  # a becomes most recently used.
            cache.get(c)
            self.assertIn(a.lower(), cache.cache)
            self.assertNotIn(b.lower(), cache.cache)
            self.assertIn('source', cache.cache)
            self.assertTrue(Path(cache.index[b.lower()]).is_file())
            with patch.object(uv, 'channel_sample', side_effect=AssertionError('warm frame must load saved pixels')):
                warm = cache.get(b)
            self.assertEqual(np.dtype('float32'), warm.dtype)
            self.assertEqual(2, len(cache.virtual_cache))
            self.assertEqual(2 * 4 * 4 * 4 * 4, cache.virtual_bytes)
            # A separate process/cache also reads single-precision saved pixels.
            with patch.object(uv, 'channel_sample', side_effect=AssertionError('warm frame must load saved pixels')):
                fresh = render.TextureCache([td]).get(a)
            self.assertEqual(np.dtype('float32'), fresh.dtype)
            np.testing.assert_allclose(fresh, cold, atol=1 / 255)

    def test_byte_budget_evicts_even_below_entry_limit(self):
        with tempfile.TemporaryDirectory() as td, patch.object(render, 'MESH_SPRITE_DIR', td):
            Image.new('RGBA', (8, 8), 'white').save(Path(td) / 'source.png')
            one_frame_bytes = 8 * 8 * 4 * 4
            cache = render.TextureCache([td], virtual_cache_bytes=2 * one_frame_bytes)
            for index in range(12):
                cache.get(virtual(index / 17))
                self.assertLessEqual(cache.virtual_bytes, 2 * one_frame_bytes)
            self.assertEqual(2, len(cache.virtual_cache))
            self.assertEqual(13, len(cache.index))  # source + every generated frame path.
            self.assertIn('source', cache.cache)

    def test_export_loads_only_referenced_textures_with_a_bounded_lru(self):
        alive = []
        loaded = []
        peak = 0

        def load(name):
            nonlocal peak
            image = Image.new('RGBA', (8, 8), 'white')
            alive.append(weakref.ref(image))
            loaded.append(name)
            peak = max(peak, sum(ref() is not None for ref in alive))
            return image

        doc = {'textures': [f'tex_{i}' for i in range(50)], 'fps': 60, 'frames': [
            [{'tex': i, 'uv': [0, 0, 8, 8], 'pos': [0, 0], 'scale': [1, 1],
              'alpha': 1, 'blend': 'mix'}] for i in range(40)]}
        with tempfile.TemporaryDirectory() as td, patch.object(to_ss6, 'load_texture', side_effect=load):
            spec = to_ss6.convert(doc, td, 'cache_test', max_cell_size=4)
        self.assertEqual(doc['textures'][:40], loaded)
        self.assertLessEqual(peak, 33)  # next item is loaded before LRU eviction.
        self.assertFalse(any(ref() is not None for ref in alive))
        self.assertEqual(40, len(spec['cells']))


if __name__ == '__main__':
    unittest.main()
