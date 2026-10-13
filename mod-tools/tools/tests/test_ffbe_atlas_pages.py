"""Animated texture atlases must retain every cell without GPU-size overflow."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import to_ss6


class AtlasPages(unittest.TestCase):
    def check_layout(self, images, pages, max_w=2048, max_h=4096):
        seen = set()
        for (width, height), positions in pages:
            self.assertLessEqual(width, max_w)
            self.assertLessEqual(height, max_h)
            self.assertEqual(0, width & (width - 1))
            self.assertEqual(0, height & (height - 1))
            rectangles = []
            for key, (x, y) in positions.items():
                self.assertNotIn(key, seen)
                seen.add(key)
                w, h = images[key].size
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + w, width)
                self.assertLessEqual(y + h, height)
                for left, top, right, bottom in rectangles:
                    self.assertTrue(x + w <= left or right <= x or y + h <= top or bottom <= y,
                                    f'Overlapping cells on atlas page: {key}')
                rectangles.append((x, y, x + w, y + h))
        self.assertEqual(set(images), seen)

    def test_wide_short_cell_does_not_clip_in_legacy_fast_path(self):
        images = {'wide': Image.new('RGBA', (128, 1))}
        self.check_layout(images, to_ss6.pack_pages(images))

    def test_oversized_cell_rejected_before_legacy_fast_path(self):
        for size in ((2049, 1), (1, 4097)):
            with self.subTest(size=size), self.assertRaises(ValueError):
                to_ss6.pack_pages({'oversized': Image.new('RGBA', size)})

    def test_pages_have_no_overlap_and_keep_every_cell(self):
        sizes = ((64, 64), (32, 63), (31, 63), (64, 7), (40, 30), (20, 30), (7, 4))
        images = {i: Image.new('RGBA', size) for i, size in enumerate(sizes)}
        pages = to_ss6.pack_pages(images, max_w=64, max_h=128)
        self.assertGreater(len(pages), 1)
        self.check_layout(images, pages, max_w=64, max_h=128)
        self.assertEqual(pages, to_ss6.pack_pages(images, max_w=64, max_h=128))

    def test_convert_cell_keys_resolve_across_all_texture_pages(self):
        colors = ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255))
        images = {f'frame{i}.png': Image.new('RGBA', (64, 64), color) for i, color in enumerate(colors)}
        frames = [[{'tex': i, 'uv': [0, 0, 64, 64], 'pos': [0, 0], 'scale': [1, 1],
                    'rot': 0, 'alpha': 1, 'blend': 'mix'}] for i in range(4)]
        doc = {'fps': 60, 'frameCount': 4, 'textures': list(images), 'frames': frames}
        packer = to_ss6.pack_pages
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(to_ss6, 'load_texture', side_effect=lambda name: images[name].copy()), \
             patch.object(to_ss6, 'pack_pages', side_effect=lambda cells: packer(cells, max_w=64, max_h=64)):
            spec = to_ss6.convert(doc, directory, 'animated_fixture')
            self.assertEqual(4, len(spec['cellmaps']))
            self.assertEqual(4, spec['conversionAudit']['atlasPages'])
            self.assertEqual(spec, json.loads((Path(directory) / 'spec.json').read_text(encoding='utf8')))
            cell_colors = {}
            for page in spec['cellmaps']:
                texture = Path(directory) / page['textureFile']
                width, height = map(int, page['pixelSize'])
                self.assertEqual(width * height * 4, texture.stat().st_size)
                with Image.open(texture.with_suffix('.png')) as atlas:
                    for cell in page['cells']:
                        x, y = map(int, cell['pos'])
                        w, h = map(int, cell['size'])
                        cell_colors[cell['name']] = atlas.getpixel((x + w // 2, y + h // 2))
            animation = next(a for a in spec['animations'] if not a.get('isSetup'))
            names = [name for _, name in animation['parts']['mix_0']['Cell']]
            self.assertEqual(list(colors), [cell_colors[name] for name in names])
            self.assertEqual(spec['cellmaps'][0]['cells'], spec['cells'])


if __name__ == '__main__':
    unittest.main()
