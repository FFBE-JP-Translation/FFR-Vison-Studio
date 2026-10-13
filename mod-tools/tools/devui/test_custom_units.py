import base64
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / 'ffbe2ss6')]
import custom_units as custom
from ffbe_frames import load_unit
from build_sprites import Sheets, build, BATTLE_ANIMS


def make_spec(detail, form, key, name, units):
    return {'id': 13500, 'key': key, 'en': name, 'ffbe': {}, 'skills': {}, 'lb_custom': {}}


class CustomUnits(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patch = patch.object(custom, 'ROOT', self.root); self.patch.start()
        image = Image.new('RGBA', (192, 128))
        for n, color in enumerate(['red', 'green', 'blue', 'yellow', 'purple', 'white']):
            image.paste(color, ((n % 3) * 64 + 16, (n // 3) * 64 + 4, (n % 3) * 64 + 48, (n // 3) * 64 + 60))
        out = io.BytesIO(); image.save(out, 'PNG')
        self.body = {'unit': deepcopy(custom.UNIT_TEMPLATE), 'animations': deepcopy(custom.ANIMATION_TEMPLATE), 'sheet': base64.b64encode(out.getvalue()).decode()}

    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()

    def create(self):
        return custom.prepare(self.body, [], {'skills': []}, make_spec)

    def test_import_builds_sprite_studio_motion_with_feet_anchor(self):
        spec, warnings, dest = self.create()
        fid = spec['ffbe']['id']
        sheet = load_unit(str(dest / 'sprites' / fid), fid)
        atlas, built = build(Sheets(sheet), BATTLE_ANIMS, 'test', 2048)
        lb = next(a for a in built['animations'] if a['name'] == 'LB1')
        self.assertEqual(48, lb['frameCount'])
        self.assertEqual([0, 12, 24], [key[0] for key in lb['parts']['part_0']['Cell']])
        self.assertEqual(-.5, built['cells'][0]['pivot'][1])
        self.assertIsNotNone(atlas.getbbox())
        source = json.loads((dest / 'resonance.json').read_text())
        self.assertEqual([12, 24], source['hitFrames'])
        self.assertEqual(100, sum(source['hitPercents']))
        self.assertEqual(['Light'], source['elements'])
        self.assertEqual('2 hits of Light physical damage to all enemies.', spec['lb_custom']['desc'])
        self.assertEqual(1, source['moveType'])
        self.assertTrue(any('magic' in w for w in warnings))
        self.assertTrue((dest / 'unit.json').is_file())

    def test_duplicate_does_not_overwrite(self):
        spec, warnings, dest = self.create()
        original = (dest / 'unit.json').read_bytes()
        self.body['unit']['name'] = 'Replacement'
        with self.assertRaisesRegex(ValueError, 'already exists'): self.create()
        self.assertEqual(original, (dest / 'unit.json').read_bytes())

    def test_new_custom_unit_does_not_reuse_deleted_units_sprite_identity(self):
        first, _, _ = self.create()
        self.body['unit']['key'] = 'another_vision'
        second, _, _ = self.create()
        self.assertNotEqual(first['ffbe']['id'], second['ffbe']['id'])

    def test_invalid_inputs_leave_no_imported_unit(self):
        original = deepcopy(self.body)
        cases = [
            ('key', lambda: self.body['unit'].update(key='../escape')),
            ('frame', lambda: self.body['animations']['animations']['attack'][0].update(frame=99)),
            ('timing', lambda: self.body['unit']['resonance'].update(hitFrames=[48])),
            ('order', lambda: self.body['unit']['resonance'].update(hitFrames=[24, 12])),
            ('stats', lambda: self.body['unit']['stats'].update(Attack=-1)),
            ('sheet', lambda: self.body.update(sheet='not a PNG')),
            ('missing motion', lambda: self.body['animations']['animations'].pop('limitBurst')),
            ('oversized grid', lambda: self.body['animations'].update(frameSize=[1, 1])),
            ('ability', lambda: self.body['unit'].update(skills=[99999999])),
        ]
        for name, change in cases:
            with self.subTest(name=name):
                self.body = deepcopy(original); change()
                with self.assertRaises(ValueError): self.create()
                self.assertFalse((self.root / 'units/custom/my_vision').exists())

    def test_rectangles_support_irregular_atlases(self):
        self.body['animations'].pop('frameSize')
        self.body['animations']['frames'] = [{'rect': [n % 3 * 64 + 16, n // 3 * 64 + 4, 32, 56], 'pivot': [16, 56]} for n in range(6)]
        spec, _, dest = self.create()
        atlas, cgg, anims = load_unit(str(dest / 'sprites' / spec['ffbe']['id']), spec['ffbe']['id'])
        self.assertEqual(-56, cgg[0][0]['yPos'])
        self.assertEqual(48, sum(s['delay'] for s in anims['limitatk']))


if __name__ == '__main__': unittest.main()
