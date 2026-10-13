"""Source render-state selectors must not be confused with alpha modules."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import ibmb


class NativeBlend(unittest.TestCase):
    def source(self, name):
        path = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec' / name
        if not path.is_file():
            self.skipTest('Optional local FFBE source fixture is not distributed')
        return ibmb.parse(str(path)), path.read_bytes()

    def test_source_border_uses_additive_blend_and_independent_alpha_curve(self):
        effect, raw = self.source('lb_rarity_NV_frame_effect_240F_orange.bmb')
        for index in (4, 5, 6, 7):
            emitter = effect.chunks[index]
            self.assertEqual(3, struct.unpack_from('<I', raw, emitter.offset + 0x198)[0])
            self.assertEqual(2, emitter.blend)
            self.assertEqual('add', ibmb.BLEND_NAMES[emitter.blend])

    def test_rain_fina_mixes_galaxy_and_models_but_adds_sweeps(self):
        prefix = 'lb_100032707_FFBE_NV_rainking_and_3rdfina_'
        back, _ = self.source(prefix + 'back_center.bmb')
        self.assertEqual([1, 1], [back.chunks[i].blend for i in (3, 4)])
        self.assertEqual([2] * 6, [back.chunks[i].blend for i in (7, 8, 9, 11, 12, 13)])
        unit, _ = self.source(prefix + 'front_unit.bmb')
        self.assertEqual([1] * 3, [unit.chunks[i].blend for i in (45, 46, 47)])
        self.assertEqual([2, 2], [unit.chunks[i].blend for i in (21, 23)])
        self.assertEqual(3, unit.chunks[48].blend)
        self.assertEqual(1, unit.chunks[50].blend)


if __name__ == '__main__':
    unittest.main()
