"""Atlas packaging regression tests; opt in to actual cooked asset readbacks."""
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
sys.path.insert(0, str(ROOT / 'tools'))
import make_vision_mod as builder
sys.path.insert(0, str(ROOT / 'tools/ffbe_effects'))
import to_ss6


def fixture(name, paged=True):
    pages = []
    for index, size in enumerate(([4, 4], [8, 2]) if paged else ([4, 4],)):
        suffix = f'_{index}' if index else ''
        pages.append({'cellmapName': name + suffix, 'imagePath': f'{name}_tex{suffix}.png',
                      'textureFile': f'tex{suffix}.bgra', 'pixelSize': size,
                      'cells': [{'name': f'cell_{index}', 'pos': [0, 0], 'size': size, 'pivot': [0, 0]}]})
    spec = {**pages[0], 'animePackName': name,
            'model': {'parts': [{'name': 'root', 'parent': -1, 'type': 'Null'},
                                {'name': 'sprite', 'parent': 0, 'type': 'Normal'}]},
            'animations': [{'name': 'effect', 'fps': 60, 'frameCount': 2, 'canvas': [64, 64],
                            'pivot': [0, 0], 'parts': {'sprite': {
                                'Cell': [[0, 'cell_0'], [1, f'cell_{len(pages)-1}']]}}}]}
    if paged:
        spec['cellmaps'] = pages
    return spec


def write_fixture(folder, spec):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'spec.json').write_text(json.dumps(spec), encoding='utf-8')
    for index, page in enumerate(spec.get('cellmaps', [spec])):
        (folder / page['textureFile']).write_bytes(bytes([index * 70, 30, 255, 200]) * int(page['pixelSize'][0] * page['pixelSize'][1]))


def field(data, name):
    return next(p['Value'] for p in data if p['Name'] == name)


def runtime_map_id(value_bytes):
    """SS6 GetSsRefCell -> FSsValue::get<int> for our compact zero-temp header."""
    if value_bytes[:3] != bytes.fromhex('80090e'):
        raise ValueError('unexpected FSsValue property header')
    kind = value_bytes[3]
    if kind == 2:  # IntType reads the int32 union payload directly.
        return struct.unpack_from('<i', value_bytes, 4)[0]
    if kind == 3:  # FloatType reads Int_temp, NOT a conversion of _Float.
        return 0  # This header serializes all temporary properties as zero.
    raise ValueError('mapId must be a numeric FSsValue')


class EffectTextureCommands(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def commands(self, spec):
        write_fixture(self.folder, spec)
        with patch.object(builder, 'run') as run:
            builder.build_effect_project('atlas_test', str(self.folder), 13110)
        return [call.args[0][len(builder.FFRDT):] for call in run.call_args_list]

    def test_legacy_single_page_keeps_texture_name(self):
        spec = fixture('atlas_test', paged=False)
        del spec['textureFile']  # Existing specs only supplied tex.bgra implicitly.
        (self.folder / 'tex.bgra').write_bytes(bytes(4 * 4 * 4))
        (self.folder / 'spec.json').write_text(json.dumps(spec), encoding='utf-8')
        with patch.object(builder, 'run') as run:
            builder.build_effect_project('atlas_test', str(self.folder), 13110)
        commands = [call.args[0][len(builder.FFRDT):] for call in run.call_args_list]
        self.assertEqual([c[0] for c in commands], ['make-ss6', 'make-texture'])
        self.assertEqual(commands[1][3:5], ['4', '4'])
        self.assertTrue(commands[1][5].endswith('atlas_test_tex.uasset'))

    def test_all_pages_have_matching_payloads_dimensions_and_object_names(self):
        commands = self.commands(fixture('atlas_test'))
        self.assertEqual([c[0] for c in commands], ['make-ss6', 'make-texture', 'make-texture'])
        second = commands[2]
        self.assertTrue(second[2].endswith('tex_1.bgra'))
        self.assertEqual(second[3:5], ['8', '2'])
        self.assertTrue(second[5].endswith('atlas_test_tex_1.uasset'))
        self.assertEqual(second[7], '/Game/Chara/effect/atlas_test/atlas_test_tex_1')
        self.assertIn('summon13110_tex=atlas_test_tex_1', second)

    def test_invalid_second_payload_fails_before_any_cooked_output(self):
        write_fixture(self.folder, fixture('atlas_test'))
        (self.folder / 'tex_1.bgra').write_bytes(b'short')
        with patch.object(builder, 'run') as run, self.assertRaisesRegex(ValueError, 'atlas 1 BGRA payload'):
            builder.build_effect_project('atlas_test', str(self.folder), 13110)
        run.assert_not_called()


class EffectDrawOrder(unittest.TestCase):
    def test_nested_float_map_id_does_not_convert_implicitly_in_the_host(self):
        old_value = bytes.fromhex('80090e03') + struct.pack('<f', 1.)
        self.assertEqual(1., struct.unpack_from('<f', old_value, 4)[0])
        self.assertEqual(0, runtime_map_id(old_value))
        fixed_value = bytes.fromhex('80090e02') + struct.pack('<i', 1)
        self.assertEqual(1, runtime_map_id(fixed_value))

    def test_overlapping_layers_keep_source_order_in_host_priority_sort(self):
        # SS6 1.6.20 sorts equal-Z parts in descending array-index order,
        # while Priority sorts equal priorities in ascending index order.
        # Two opaque layers with a glow between them expose that reversal.
        doc = {'fps': 60, 'textures': ['red.png', 'glow.png', 'blue.png'],
               'frames': [[{'tex': i, 'uv': [0, 0, 4, 4], 'pos': [0, 0],
                            'scale': [1, 1], 'blend': blend}
                           for i, blend in enumerate(('mix', 'add', 'mix'))]]}
        colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]
        with tempfile.TemporaryDirectory() as folder, patch.object(
                to_ss6, 'load_texture', side_effect=lambda name: Image.new('RGBA', (4, 4), colors[doc['textures'].index(name)])):
            spec = to_ss6.convert(doc, folder, 'overlap', scale=1.)
        self.assertEqual(['Priority', 'Priority'], [a['sortMode'] for a in spec['animations']])
        parts = spec['model']['parts'][1:]
        self.assertEqual(['mix_0', 'add_1', 'mix_2'], [p['name'] for p in parts])
        self.assertEqual(['Mix', 'Add', 'Mix'], [p['blend'] for p in parts])
        # The final opaque blue layer must cover both earlier layers. With
        # the inherited Z mode the red first layer incorrectly ends on top.
        priority_order = sorted(enumerate(parts, 1), key=lambda item: item[0])
        depth_order = sorted(enumerate(parts, 1), key=lambda item: -item[0])
        self.assertEqual('mix_2', priority_order[-1][1]['name'])
        self.assertEqual('mix_0', depth_order[-1][1]['name'])


@unittest.skipUnless(os.environ.get('FFR_TEST_COOKED_SS6') == '1', 'set FFR_TEST_COOKED_SS6=1 for serialized asset regression')
class CookedCellmaps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(os.environ.get('FFR_SS6_TEST_WORK', ROOT / 'build/test-effect-cellmaps')).resolve()
        cls.folder.mkdir(parents=True, exist_ok=True)
        cls.mapping = cls.folder / 'Mappings.usmap'
        shutil.copy2(builder.USMAP, cls.mapping)

    def readback(self, path):
        output = self.folder / (path.stem + '.json')
        subprocess.run(builder.FFRDT + ['tojson', str(path), str(output), '--usmap', str(self.mapping)], check=True)
        return json.loads(output.read_text(encoding='utf-8'))

    def check_project(self, name, paged, sort_mode=None):
        spec = fixture(name, paged)
        if sort_mode is not None:
            spec['animations'][0]['sortMode'] = sort_mode
        spec_dir = self.folder / name
        write_fixture(spec_dir, spec)
        with patch.object(builder, 'OUT', str(self.folder / 'assets')), patch.object(builder, 'USMAP', str(self.mapping)):
            builder.build_effect_project(name, str(spec_dir), 13110)
        out = self.folder / 'assets/FFRS/Content/Chara/effect' / name
        cooked = self.readback(out / f'{name}.uasset')
        data = cooked['Exports'][0]['Data']
        maps = field(data, 'CellmapList')
        pages = spec.get('cellmaps', [spec])
        names = [p['cellmapName'] + '.ssce' for p in pages]
        self.assertEqual([p['Value'] for p in field(data, 'CellmapNames')], names)
        pack = field(data, 'AnimeList')[0]['Value']
        settings = field(field(pack, 'AnimeList')[0]['Value'], 'Settings')
        self.assertEqual(sort_mode or 'Z', field(settings, 'SortMode').split('::')[-1])
        self.assertEqual([p['Value'] for p in field(pack, 'CellmapNames')], names)
        self.assertEqual(len(maps), len(pages))
        texture_refs = []
        for index, (cm, page) in enumerate(zip(maps, pages)):
            values = cm['Value']
            self.assertEqual(field(values, 'Filename'), names[index])
            self.assertEqual(field(values, 'CellMapNameEx'), names[index])
            self.assertEqual(field(values, 'CellMapName'), page['cellmapName'])
            self.assertEqual(field(values, 'ImagePath'), page['imagePath'])
            size = field(values, 'PixelSize')[0]['Value']
            self.assertEqual([size['X'], size['Y']], page['pixelSize'])
            self.assertEqual(field(field(values, 'Cells')[0]['Value'], 'CellName'), f'cell_{index}')
            ref = field(values, 'Texture')
            texture_refs.append(ref)
            texture = cooked['Imports'][-ref-1]
            suffix = f'_{index}' if index else ''
            self.assertEqual(texture['ObjectName'], f'{name}_tex{suffix}')
            self.assertEqual(cooked['Imports'][-texture['OuterIndex']-1]['ObjectName'], f'/Game/Chara/effect/{name}/{name}_tex{suffix}')
            self.assertIn(ref, cooked['Exports'][0]['CreateBeforeSerializationDependencies'])
            texture_json = self.readback(out / f'{name}_tex{suffix}.uasset')
            export = texture_json['Exports'][0]
            self.assertEqual(export['ObjectName'], f'{name}_tex{suffix}')
            extras = base64.b64decode(export['Extras'])
            resource = texture_json['DataResources'][0]
            payload_start = resource['SerialOffset'] - (export['SerialSize'] - len(extras))
            self.assertEqual(extras[payload_start:payload_start + resource['SerialSize']], (spec_dir / page['textureFile']).read_bytes())
        self.assertEqual(len(set(texture_refs)), len(pages))
        # FSsValue serializes hash payloads in Extras. Read the actual bytes,
        # including mapId, rather than trusting the input JSON or placeholders.
        tail = base64.b64decode(cooked['Exports'][0]['Extras'])
        offset = 0
        selected = []
        for _ in range(2):
            self.assertEqual(struct.unpack_from('<i', tail, offset)[0], 2)
            offset += 4
            self.assertEqual(cooked['NameMap'][struct.unpack_from('<i', tail, offset)[0]], 'mapId')
            offset += 8
            self.assertEqual(tail[offset:offset+4], bytes.fromhex('80090e02'))
            map_id = runtime_map_id(tail[offset:offset+8])
            offset += 8
            self.assertEqual(cooked['NameMap'][struct.unpack_from('<i', tail, offset)[0]], 'name')
            offset += 12
            length = struct.unpack_from('<i', tail, offset)[0]
            offset += 4
            cell = tail[offset:offset+length-1].decode('ascii')
            offset += length
            selected.append((map_id, cell))
        self.assertEqual(offset, len(tail))
        self.assertEqual(selected, [(0, 'cell_0'), (len(pages)-1, f'cell_{len(pages)-1}')])

    def test_two_pages_resolve_distinct_texture_imports_and_cell_keys(self):
        self.check_project('ss6_two_page_fixture', True, 'Priority')

    def test_legacy_spec_remains_one_map_with_zero_map_indices(self):
        self.check_project('ss6_legacy_fixture', False)

    def test_duplicate_names_and_unknown_cell_keys_fail_without_writing(self):
        for failure in ('duplicate', 'unknown'):
            spec = fixture('invalid_' + failure)
            if failure == 'duplicate':
                spec['cellmaps'][1]['cells'][0]['name'] = 'cell_0'
            else:
                spec['animations'][0]['parts']['sprite']['Cell'][1][1] = 'missing_cell'
            folder = self.folder / ('invalid_' + failure)
            write_fixture(folder, spec)
            output = folder / 'never_written.uasset'
            result = subprocess.run(builder.FFRDT + ['make-ss6', str(ROOT / 'extracted/legacy/FFRS/Content/Chara/summon/summon13110/summon13110.uasset'),
                str(folder / 'spec.json'), str(output), '/Game/Chara/summon/summon13110/summon13110',
                '/Game/Chara/effect/invalid/invalid', 'summon13110=invalid', '--usmap', str(self.mapping)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('globally unique' if failure == 'duplicate' else 'unknown cell', result.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
