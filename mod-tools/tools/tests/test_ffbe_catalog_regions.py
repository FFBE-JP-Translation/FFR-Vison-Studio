"""Matching move IDs must not silently cross regional presentation graphs."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from ffbe_effects import catalog


class CatalogRegions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        fields = self.directory/'fields.json'
        fields.write_text(json.dumps({'id': 'ability_id', 'frames': 'effect_frames'}))
        self.gl = {
            'F_ABILITY_MST': [{'id': '1', 'frames': '40:7:1:5:7'}, {'id': '2', 'frames': '0:7:1:3:0'}],
            'F_EFFECT_GROUP_MST': [{'qIy86WvJ': '7', 'frames': '28:8:99999999:1:2:2:40:-40', '1fVZ3rKd': '28:100:1'}],
            'F_EFFECT_MST': [{'h5t4yBm2': '8', 'I1B7wNWc': '5', '2HjxCGo6': 'global.bmb', 'avX1k34K': '150'}],
        }
        self.jp = {
            'F_ABILITY_MST': [{'ability_id': '1', 'effect_frames': '41:7:2:4:0'}],
            'F_EFFECT_GROUP_MST': [{'qIy86WvJ': '7', 'effect_frames': '29:8:99999999:1:5:5:0:0', '1fVZ3rKd': '29:200:1'}],
            'F_EFFECT_MST': [{'h5t4yBm2': '8', 'I1B7wNWc': '5', '2HjxCGo6': 'japan.bmb', 'avX1k34K': '100'}],
        }
        self.write_gl()
        self.state = patch.multiple(catalog, _cache={}, _indexes={}, _table_identities={},
                                    RAW_SOURCES={'GL_2024': self.directory, 'JP_2024': self.directory})
        self.state.start()
        self.names = patch.object(catalog.ffbe_live, 'FIELDS', str(fields)); self.names.start()
        self.loader = patch.object(catalog.ffbe_live, 'load_table', side_effect=lambda name:
                                   {'rows': self.jp[name], 'file': 'live-fixture.dat'}).start()

    def write_gl(self):
        for name, rows in self.gl.items():
            (self.directory/(name+'.txt')).write_text('\n'.join(json.dumps(row) for row in rows)+'\n')

    def tearDown(self):
        patch.stopall()
        self.temp.cleanup()

    def test_all_three_master_layers_follow_the_requested_region(self):
        gl = catalog.skill_effects('ability', '1', source='GL_2024')
        jp = catalog.skill_effects('ability', '1', source='JP_CLIENT')
        self.assertEqual(40, gl['groups'][0]['frame'])
        self.assertEqual(41, jp['groups'][0]['frame'])
        self.assertEqual('global.bmb', gl['groups'][0]['group']['effects'][0]['file'])
        self.assertEqual('japan.bmb', jp['groups'][0]['group']['effects'][0]['file'])
        self.assertEqual('100', gl['groups'][0]['group']['sounds'][0]['seId'])
        self.assertEqual('200', jp['groups'][0]['group']['sounds'][0]['seId'])
        self.assertEqual('GL_2024', gl['groups'][0]['group']['source'])
        self.assertEqual(64, len(gl['sourceTables']['F_ABILITY_MST']['sha256']))
        self.assertTrue(gl['sourceTables']['F_EFFECT_GROUP_MST']['path'].endswith('F_EFFECT_GROUP_MST.txt'))

    def test_default_behavior_remains_live_jp_and_explicit_missing_never_falls_back(self):
        self.assertEqual(41, catalog.skill_effects('ability', '1')['groups'][0]['frame'])
        self.assertIsNone(catalog.skill_effects('ability', '2', source='JP_CLIENT'))
        self.assertIsNotNone(catalog.skill_effects('ability', '2', source='GL_2024'))
        with self.assertRaisesRegex(ValueError, 'no regional fallback'):
            catalog.skill_effects('ability', '1', source='future-region')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            catalog.skill_effects('ability', '1', source='JP_CLIENT', region='GL')

    def test_standard_group_read_can_select_the_same_explicit_region(self):
        gl = catalog.group_detail('7', region='GL')
        jp = catalog.group_detail('7', source='JP_CLIENT')
        self.assertEqual(28, gl['effects'][0]['frame'])
        self.assertEqual(29, jp['effects'][0]['frame'])
        self.assertEqual('GL_2024', gl['source'])

    def test_cgg_effect_is_preserved_with_its_adapter_requirement(self):
        self.gl['F_EFFECT_MST'][0].update(I1B7wNWc='1', **{'2HjxCGo6': 'unit.png:parts.csv:frames.csv'})
        self.write_gl()
        effect = catalog.group_detail('7', source='GL_2024')['effects'][0]
        self.assertFalse(effect['exists'])
        self.assertEqual('1', effect['effectType'])
        self.assertIn('CGG/CGS', effect['sourceIssue'])
        self.assertEqual(['unit.png', 'parts.csv', 'frames.csv'], effect['sourceDependencies'])

    def test_cached_indexes_do_not_cross_source_or_survive_replaced_fixture_rows(self):
        first = catalog.group_rows('GL_2024')
        self.assertIs(first, catalog.group_rows('GL_2024'))
        self.assertNotEqual(first['7']['effect_frames'], catalog.group_rows('JP_CLIENT')['7']['effect_frames'])
        rows = {'F_EFFECT_GROUP_MST': [{'qIy86WvJ': '99'}]}
        with patch.object(catalog, 'table', side_effect=rows.__getitem__):
            self.assertEqual({'99': rows['F_EFFECT_GROUP_MST'][0]}, catalog.group_rows())


if __name__ == '__main__':
    unittest.main()
