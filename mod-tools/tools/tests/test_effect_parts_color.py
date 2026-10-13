"""Identity parts-color routing, including native typed cooked-key readbacks."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/ffbe_effects'))
import to_ss6

IDENTITY = {'target': 'Whole', 'blendType': 'Mul', 'rgba': [255] * 4, 'rate': 1.0}
CLI = ['dotnet', str(ROOT / 'src/ffr-dt/bin/Release/net8.0/ffr-dt.dll')]
DONOR = ROOT / 'extracted/legacy/FFRS/Content/Chara/summon/summon13110/summon13110.uasset'
DONOR_PACKAGE = '/Game/Chara/summon/summon13110/summon13110'


def field(data, name):
    return next(p['Value'] for p in data if p['Name'] == name)


def fixture(folder):
    pixels = [(16, 64, 255, 128), (180, 90, 20, 255)]
    doc = {'fps': 60, 'textures': ['blue', 'orange'], 'frames': []}
    for frame in range(2):
        doc['frames'].append([{'tex': i, 'uv': [0, 0, 4, 4], 'pos': [3, -2],
                              'scale': [-1 if i else 1, 0.5], 'rot': 12,
                              'alpha': 0.5 - frame * 0.25, 'blend': blend}
                             for i, blend in enumerate(('add', 'mix'))])
    with patch.object(to_ss6, 'load_texture', side_effect=lambda name: Image.new(
            'RGBA', (4, 4), pixels[doc['textures'].index(name)])):
        return to_ss6.convert(doc, folder, 'neutral_color_fixture', scale=1.)


def read_keys(cooked):
    """Consume FSsValue payloads in the actual SS6 serialization traversal order.

    Numeric accessors match SsValue.h: get<int>() on FloatType returns the
    separately serialized Int_temp (zero in compact hash entries), not _Float.
    Colors require ColorType's four uint32 RGBA channels; bytes are invalid.
    """
    tail = memoryview(base64.b64decode(cooked['Exports'][0]['Extras']))
    offset = 0
    def take(fmt):
        nonlocal offset
        result = struct.unpack_from(fmt, tail, offset)
        offset += struct.calcsize(fmt)
        return result[0] if len(result) == 1 else result
    def value(kind):
        nonlocal offset
        if kind == 1:
            length = take('<i')
            if length <= 0: raise AssertionError('fixture expects ASCII FString')
            result = bytes(tail[offset:offset+length-1]).decode('ascii')
            offset += length
            return result
        if kind == 2: return take('<i')
        if kind == 3: return take('<f')
        if kind == 8: return list(take('<4I'))
        if kind != 5: raise AssertionError(f'unsupported native type {kind}')
        result = {}
        for _ in range(take('<i')):
            index, number = take('<ii')
            if number != 0: raise AssertionError('unexpected numbered hash key')
            name = cooked['NameMap'][index]
            header = bytes(tail[offset:offset+4]); offset += 4
            if header[:3] != bytes.fromhex('80090e'): raise AssertionError('unexpected FSsValue header')
            kind = header[3]
            decoded = value(kind)
            if name in ('target', 'blendType', 'mapId') and kind != 2:
                raise AssertionError(f'{name}: native integer accessor would not read this payload')
            if name == 'rgba' and kind != 8: raise AssertionError('native color pointer needs ColorType')
            result[name] = decoded
        return result
    all_keys = {}
    for pack in field(cooked['Exports'][0]['Data'], 'AnimeList'):
        for anim in field(pack['Value'], 'AnimeList'):
            name = field(anim['Value'], 'AnimationName')
            for part in field(anim['Value'], 'PartAnimes'):
                part_name = field(part['Value'], 'PartName')
                for attr in field(part['Value'], 'Attributes'):
                    tag = field(attr['Value'], 'Tag').split('::')[-1]
                    keys = []
                    for key in field(attr['Value'], 'Key'):
                        data = field(key['Value'], 'Value')
                        kind = field(data, 'Type').split('::')[-1]
                        decoded = value({'FloatType': 3, 'HashType': 5}[kind])
                        keys.append([field(key['Value'], 'Time'), decoded])
                    all_keys[(name, part_name, tag)] = keys
    if offset != len(tail): raise AssertionError('unconsumed native payload bytes')
    return all_keys


class ExportPartsColor(unittest.TestCase):
    def test_only_additive_setup_selects_identity_material_without_changing_source_data(self):
        with tempfile.TemporaryDirectory() as folder:
            spec = fixture(folder)
            setup = spec['animations'][1]['parts']
            self.assertEqual([[0, IDENTITY]], setup['add_0']['PartsColor'])
            self.assertNotIn('PartsColor', setup['mix_1'])
            self.assertNotIn('PartsColor', setup['root'])
            for part in ('add_0', 'mix_1'):
                action = spec['animations'][0]['parts'][part]
                self.assertNotIn('PartsColor', action)
                self.assertEqual([[0, 0.5], [1, 0.25]], action['Alpha'])
                self.assertEqual([[0, 3.]], action['Posx'])
                self.assertEqual([[0, -2.]], action['Posy'])
            with Image.open(Path(folder) / 'tex.png') as image:
                found = set(image.convert('RGBA').getdata())
            self.assertIn((16, 64, 255, 128), found)
            self.assertIn((180, 90, 20, 255), found)


@unittest.skipUnless(os.environ.get('FFR_TEST_COOKED_SS6') == '1', 'requires cooked SS6 fixture opt-in')
class CookedPartsColor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(os.environ.get('FFR_SS6_COLOR_TEST_WORK', tempfile.mkdtemp(prefix='ffr-parts-color-')))
        cls.folder.mkdir(parents=True, exist_ok=True)
        # Never open the shared mapping: UAssetAPI requests read/write access.
        cls.mapping = cls.folder / 'Mappings.usmap'
        mapping = Path(os.environ.get('FFR_SS6_COLOR_TEST_MAPPING', ROOT / 'build/rain-fina-motion/multicellmap/fixtures/Mappings.usmap'))
        if mapping.resolve() != cls.mapping.resolve(): shutil.copyfile(mapping, cls.mapping)
        cls.spec = fixture(cls.folder)

    def cook(self, name, spec):
        source = self.folder / (name + '-spec.json')
        source.write_text(json.dumps(spec), encoding='utf8')
        cooked = self.folder / (name + '.uasset')
        subprocess.run(CLI + ['make-ss6', str(DONOR), str(source), str(cooked), DONOR_PACKAGE,
                             '/Game/Chara/effect/' + name + '/' + name,
                             'summon13110=' + name, '--usmap', str(self.mapping)], check=True)
        output = self.folder / (name + '-readback.json')
        subprocess.run(CLI + ['tojson', str(cooked), str(output), '--usmap', str(self.mapping)], check=True)
        return json.loads(output.read_text(encoding='utf8'))

    def test_typed_color_selects_stock_addmul_and_preserves_alpha_geometry_and_cells(self):
        cooked = self.cook('identity_color', self.spec)
        keys = read_keys(cooked)
        native = keys[('Setup', 'add_0', 'PartsColor')][0][1]
        self.assertEqual({'target': 0, 'blendType': 1, 'color': {'rgba': [255]*4, 'rate': 1.0}}, native)
        # These are the exact indices read by GetSsPartsColorValue and the
        # Add/Mul branch of SsPlayerComponent::GetBaseMaterialComp.
        self.assertEqual(0, native['target'])
        self.assertEqual(1, native['blendType'])
        defaults = (ROOT / 'extracted/pak/FFRS/Config/DefaultGame.ini').read_text(encoding='utf8')
        additive = defaults.split('),Add=(', 1)[1].split('),Sub=(', 1)[0]
        self.assertIn("/SpriteStudio6/Component_Default/M_Ss_Component_Default_AddMul.", additive.split("Mul=", 1)[1].split(",", 1)[0])
        self.assertIn('AddInv_EmissiveBoost', additive)
        legacy = deepcopy(self.spec)
        del legacy['animations'][1]['parts']['add_0']['PartsColor']
        old = read_keys(self.cook('legacy_no_color', legacy))
        self.assertEqual(old, {k:v for k,v in keys.items() if k[2] != 'PartsColor'})
        self.assertEqual([[0, .5], [1, .25]], keys[('effect', 'add_0', 'Alpha')])
        # Neutral white retains the animated opacity; it does not square it.
        self.assertEqual(127, int(native['color']['rgba'][3] * .5))

    def test_color_width_matches_real_native_unit0030_donor_bytes(self):
        # Original /Game/Chara/Unit/unit0030/unit0030 PartsColor, Extras2515:
        # rgba FName183 + header + four uint32 channels; next rate FName182
        # starts at2543. All35 native color keys use this exact black RGBA.
        # Original Extras SHA256:
        # b8b84ddd09267a61f97d27fe62ad27b1ba1d4eb5979b06f75fcdb979d53c16b6
        native = bytes.fromhex('80090e08 00000000 00000000 00000000 ff000000')
        spec = deepcopy(self.spec)
        spec['animations'][1]['parts']['add_0']['PartsColor'][0][1]['rgba'] = [0, 0, 0, 255]
        cooked = self.cook('native_color_layout', spec)
        tail = base64.b64decode(cooked['Exports'][0]['Extras'])
        rgba_name = struct.pack('<ii', cooked['NameMap'].index('rgba'), 0)
        start = tail.index(rgba_name) + 8
        self.assertEqual(native, tail[start:start+len(native)])
        rate_index, number = struct.unpack_from('<ii', tail, start+len(native))
        self.assertEqual('rate', cooked['NameMap'][rate_index])
        self.assertEqual(0, number)
        self.assertEqual([0, 0, 0, 255], read_keys(cooked)[('Setup', 'add_0', 'PartsColor')][0][1]['color']['rgba'])
        # Reproduce the rejected four-byte layout. The native-width reader
        # must reject it instead of validating an identically wrong writer.
        broken = deepcopy(cooked)
        broken['Exports'][0]['Extras'] = base64.b64encode(tail[:start+4] + bytes([0,0,0,255]) + tail[start+len(native):]).decode('ascii')
        with self.assertRaises((AssertionError, IndexError, struct.error)):
            read_keys(broken)

    def test_runtime_scale_changes_only_explicit_model_root_axes(self):
        original = deepcopy(self.spec)
        original['model']['parts'][0]['name'] = 'stage_origin'
        for animation in original['animations']:
            root = animation['parts'].pop('root')
            root.update({'Sclx': [[0, 1.5], [1, 1.25]], 'Scly': [[0, .75]]})
            animation['parts']['stage_origin'] = root
        baseline = read_keys(self.cook('runtime_scale_default', original))
        identity = deepcopy(original)
        identity['runtimeScale'] = 1.0
        self.assertEqual(baseline, read_keys(self.cook('runtime_scale_one', identity)))
        scaled = deepcopy(original)
        scaled['runtimeScale'] = .8
        actual = read_keys(self.cook('runtime_scale_eight_tenths', scaled))
        self.assertEqual(set(baseline), set(actual))
        changed = 0
        for key, expected in baseline.items():
            if key[1] == 'stage_origin' and key[2] in ('Sclx', 'Scly'):
                changed += 1
                self.assertEqual([t for t, _ in expected], [t for t, _ in actual[key]])
                for (_, before), (_, after) in zip(expected, actual[key]):
                    self.assertAlmostEqual(before * .8, after, places=6)
            else:
                self.assertEqual(expected, actual[key], key)
        self.assertEqual(4, changed)  # two axes in action and Setup
        saved = json.loads((self.folder / 'runtime_scale_eight_tenths-spec.json').read_text(encoding='utf8'))
        self.assertEqual(scaled, saved)  # adapter must not rewrite prepared input

    def test_runtime_scale_inherits_setup_axes_when_exported_action_has_none(self):
        # This is the real effect export shape: action root is Hide-only;
        # Setup supplies root axes and SS6 applies them before action channels.
        source = deepcopy(self.spec)
        source['animations'][1]['parts']['root'].update({'Sclx': [[0, 1.]], 'Scly': [[0, 1.]]})
        baseline = read_keys(self.cook('setup_scale_default', source))
        source['runtimeScale'] = .8
        actual = read_keys(self.cook('setup_scale_inherited', source))
        self.assertNotIn(('effect', 'root', 'Sclx'), actual)
        self.assertNotIn(('effect', 'root', 'Scly'), actual)
        for key, expected in baseline.items():
            if key[0:2] == ('Setup', 'root') and key[2] in ('Sclx', 'Scly'):
                self.assertEqual([0], [t for t, _ in actual[key]])
                self.assertAlmostEqual(.8, actual[key][0][1], places=6)
            else:
                self.assertEqual(expected, actual[key], key)
        # Native setup-then-action selection must retain the scaled values.
        selected = {key[2]: value for key, value in actual.items() if key[0:2] == ('Setup', 'root')}
        selected.update({key[2]: value for key, value in actual.items() if key[0:2] == ('effect', 'root')})
        for axis in ('Sclx', 'Scly'):
            self.assertAlmostEqual(.8, selected[axis][0][1], places=6)

    def test_runtime_viewport_stretches_about_source_center_with_setup_inheritance(self):
        source = deepcopy(self.spec)
        source['animations'][1]['parts']['root'].update(
            {'Sclx': [[0, 1.]], 'Scly': [[0, 1.]], 'Posx': [[0, 0.]]})
        source['runtimeScale'] = .8
        baseline = read_keys(self.cook('viewport_scalar_only', source))
        identity = deepcopy(source)
        identity['runtimeViewport'] = {'stretchX': 1., 'center': [-96., 84.]}
        self.assertEqual(baseline, read_keys(self.cook('viewport_identity', identity)))
        source['runtimeViewport'] = {'stretchX': 1.5, 'center': [-96., 84.]}
        actual = read_keys(self.cook('viewport_widescreen', source))
        self.assertEqual(set(baseline), set(actual))
        self.assertNotIn(('effect', 'root', 'Posx'), actual)
        self.assertNotIn(('effect', 'root', 'Sclx'), actual)
        changed = {('Setup', 'root', 'Sclx'), ('Setup', 'root', 'Posx')}
        for key, keys in baseline.items():
            if key not in changed: self.assertEqual(keys, actual[key], key)
        sx = actual[('Setup', 'root', 'Sclx')][0][1]
        sy = actual[('Setup', 'root', 'Scly')][0][1]
        tx = actual[('Setup', 'root', 'Posx')][0][1]
        self.assertAlmostEqual(1.2, sx, places=6)
        self.assertAlmostEqual(.8, sy, places=6)
        self.assertAlmostEqual(38.4, tx, places=5)
        for x in (-256., -96., 64.):
            self.assertAlmostEqual(.8 * (-96 + 1.5*(x+96)), tx+sx*x, places=4)
        saved = json.loads((self.folder/'viewport_widescreen-spec.json').read_text(encoding='utf8'))
        self.assertEqual(source, saved)

    def test_runtime_viewport_preserves_nonroot_and_animated_root_position_keys(self):
        source = deepcopy(self.spec)
        source['model']['parts'][0]['name'] = 'stage_origin'
        for animation in source['animations']:
            root = animation['parts'].pop('root')
            root.update({'Sclx': [[0, 2.], [1, 3.]], 'Scly': [[0, .5]],
                         'Posx': [[0, 10.], [1, -6.]], 'Posy': [[0, 20.], [1, 21.]]})
            animation['parts']['stage_origin'] = root
        baseline = read_keys(self.cook('viewport_animated_default', source))
        source['runtimeScale'] = 1.25
        source['runtimeViewport'] = {'stretchX': 1.75, 'center': [32., 84.]}
        actual = read_keys(self.cook('viewport_animated_stretch', source))
        self.assertEqual(set(baseline), set(actual))
        for key, expected in baseline.items():
            if key[1] == 'stage_origin' and key[2] in ('Sclx', 'Scly', 'Posx'):
                scale = {'Sclx': 1.25*1.75, 'Scly': 1.25, 'Posx': 1.}[key[2]]
                shift = -30. if key[2] == 'Posx' else 0.
                self.assertEqual([[t, v*scale+shift] for t, v in expected], actual[key])
            else:
                self.assertEqual(expected, actual[key], key)

    def test_runtime_viewport_rejects_invalid_or_missing_identity_transform(self):
        for label, viewport in (
            ('zero', {'stretchX': 0, 'center': [0, 0]}),
            ('negative', {'stretchX': -1, 'center': [0, 0]}),
            ('boolean', {'stretchX': True, 'center': [0, 0]}),
            ('text', {'stretchX': '1.5', 'center': [0, 0]}),
            ('nan', {'stretchX': float('nan'), 'center': [0, 0]}),
            ('center', {'stretchX': 1.5, 'center': [float('inf'), 0]}),
            ('center_bool', {'stretchX': 1.5, 'center': [0, False]}),
            ('center_length', {'stretchX': 1.5, 'center': [0]}),
            ('overflow', {'stretchX': 3e38, 'center': [3e38, 0]}),
            ('missing_position', {'stretchX': 1.5, 'center': [-96, 84]})):
            bad = deepcopy(self.spec)
            bad['animations'][1]['parts']['root'].update({'Sclx': [[0, 1.]], 'Scly': [[0, 1.]]})
            bad['runtimeViewport'] = viewport
            source = self.folder/(label+'-viewport-spec.json')
            source.write_text(json.dumps(bad), encoding='utf8')
            output = self.folder/(label+'-viewport.uasset')
            result = subprocess.run(CLI + ['make-ss6', str(DONOR), str(source), str(output), DONOR_PACKAGE,
                                    '/Game/invalid/invalid', '--usmap', str(self.mapping)], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode, label)
            self.assertIn('requires root.Posx keys' if label == 'missing_position' else 'runtimeViewport', result.stderr)
            self.assertFalse(output.exists())

    def test_runtime_scale_rejects_missing_root_keys_and_invalid_scalar(self):
        for label, scalar in (('zero', 0), ('negative', -1), ('text', '0.8'), ('nan', float('nan')), ('missing', .8)):
            bad = deepcopy(self.spec)
            bad['runtimeScale'] = scalar
            source = self.folder / (label + '-scale.json')
            source.write_text(json.dumps(bad), encoding='utf8')
            output = self.folder / (label + '-scale.uasset')
            result = subprocess.run(CLI + ['make-ss6', str(DONOR), str(source), str(output), DONOR_PACKAGE,
                                    '/Game/invalid/invalid', '--usmap', str(self.mapping)], capture_output=True, text=True)
            self.assertNotEqual(0, result.returncode, label)
            self.assertIn('requires root.Sclx keys' if label == 'missing' else 'finite positive number', result.stderr)
            self.assertFalse(output.exists())

    def test_invalid_color_payload_fails_before_writing_asset(self):
        bad = deepcopy(self.spec)
        bad['animations'][1]['parts']['add_0']['PartsColor'][0][1]['rgba'][2] = 256
        source = self.folder / 'invalid-spec.json'
        source.write_text(json.dumps(bad), encoding='utf8')
        output = self.folder / 'invalid-color.uasset'
        result = subprocess.run(CLI + ['make-ss6', str(DONOR), str(source), str(output), DONOR_PACKAGE,
                                '/Game/invalid/invalid', '--usmap', str(self.mapping)], capture_output=True, text=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('four integer bytes', result.stderr)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
