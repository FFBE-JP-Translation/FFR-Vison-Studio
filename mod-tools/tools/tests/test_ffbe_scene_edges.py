"""Scene classification follows the sampled sprite cell, not its whole atlas."""
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffbe_effects import scene


class SceneAtlasCoverage(unittest.TestCase):
    def classify_cell(self, texture, uv, scale):
        spawn = {'file': 'background.bmb', 'groupId': '42', 'frame': 0,
                 'anchor': 'screen', 'layer': 2, 'x': 0, 'y': 0, 'scale': 1.0,
                 'rotation': [0, 0, 0]}
        sprite = {'tex': 0, 'uv': uv, 'pos': [0, 0], 'scale': [scale, scale],
                  'alpha': 1.0, 'blend': 'mix', 'rot': 0.0}
        docs = {'background.bmb': {'pixelsPerUnit': 1, 'textures': ['atlas'],
                                    'frames': [[dict(sprite)] for _ in range(90)]}}
        return scene.classify([spawn], docs, lambda _: texture.copy())

    def test_opaque_cell_in_transparent_atlas_is_a_replacement_background(self):
        texture = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        texture.paste((30, 60, 90, 255), (0, 0, 16, 16))
        result = self.classify_cell(texture, [0, 0, 16, 16], 40)
        self.assertEqual(result['kind'], 'replacement_background')

    def test_transparent_cell_in_opaque_atlas_does_not_replace_battlefield(self):
        texture = Image.new('RGBA', (64, 64), (30, 60, 90, 255))
        texture.paste((0, 0, 0, 0), (0, 0, 8, 8))
        result = self.classify_cell(texture, [0, 0, 8, 8], 80)
        self.assertEqual(result['kind'], 'screen_overlay')


if __name__ == '__main__':
    unittest.main()
