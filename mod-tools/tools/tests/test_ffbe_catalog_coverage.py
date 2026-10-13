"""Census denominators and source/renderer boundaries must remain distinct."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffbe_effects import catalog_coverage as census


class Tables:
    identities = {}
    errors = []

    def __init__(self, values):
        self.values = values

    def table(self, source, table):
        return self.values.get((source, table), {})


class CatalogCoverage(unittest.TestCase):
    def test_catalog_derives_units_and_forms_without_fixed_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'index.json'
            path.write_text(json.dumps([{'id': '10', 'forms': ['100', '101']},
                                        {'id': '20', 'forms': ['200']}]))
            result = census.load_catalog(path)
            self.assertEqual(['100', '101', '200'], result['forms'])
            self.assertEqual({'100': '10', '101': '10', '200': '20'}, result['owners'])
            self.assertEqual(64, len(result['identity']['sha256']))
            path.write_text(json.dumps([{'id': '10', 'forms': ['100']}, {'id': '20', 'forms': ['100']}]))
            with self.assertRaisesRegex(ValueError, 'duplicate form owner'):
                census.load_catalog(path)
            path.write_text(json.dumps([{'id': '10', 'forms': ['100', '100']}]))
            with self.assertRaises(ValueError): census.load_catalog(path)

    def test_requested_region_and_current_jp_frame_gate_are_not_conflated(self):
        tables = Tables({('GL_2024', 'F_ABILITY_MST'): {'1': {'effect_frames': '40:7:1:5:7'}},
                         ('JP_CLIENT', 'F_ABILITY_MST'): {'1': {'effect_frames': '41:7:1:5:7'}},
                         ('GL_2024', 'F_EFFECT_GROUP_MST'): {'7': {'effect_frames': '28:8:0:1:2:2:0:0', '1fVZ3rKd': '28:100:1'}},
                         ('GL_2024', 'F_EFFECT_MST'): {'8': {'I1B7wNWc': '5', '2HjxCGo6': 'hit.bmb'}}})
        record = {'source': 'GL_2024', 'kind': 'ability', 'id': '1', 'data': {'effect_frames': [[40]]}}
        graph = census.inspect_source_graph(record, tables)
        self.assertTrue(graph['resolved'])
        self.assertTrue(graph['semanticPlacement'])
        self.assertFalse(graph['legacyPlacement'])
        self.assertFalse(graph['jpPipelineFrameCompatible'])
        self.assertEqual(['hit.bmb'], graph['files'])
        self.assertEqual([100], graph['cues'])
        self.assertNotIn('rendered', graph)

    def test_missing_source_and_cgg_formats_cannot_become_bmb_success(self):
        record = {'source': 'GL_2024', 'kind': 'ability', 'id': '1', 'data': {}}
        self.assertFalse(census.inspect_source_graph(record, Tables({}))['resolved'])
        tables = Tables({('GL_2024', 'F_ABILITY_MST'): {'1': {'effect_frames': '0:7:1:3:0'}},
                         ('GL_2024', 'F_EFFECT_GROUP_MST'): {'7': {'effect_frames': '0:8:0:1:5:5:0:0'}},
                         ('GL_2024', 'F_EFFECT_MST'): {'8': {'I1B7wNWc': '1', '2HjxCGo6': 'unit.png:parts.csv:frames.csv'}}})
        graph = census.inspect_source_graph(record, tables)
        self.assertTrue(graph['resolved'])
        self.assertFalse(graph['bmbFormatOnly'])
        self.assertEqual(['frames.csv', 'parts.csv', 'unit.png'], graph['files'])

    def test_parser_success_and_dependency_completeness_do_not_imply_rendering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'hit.bmb').write_bytes(b'fixture')
            effect = SimpleNamespace(textures=['missing'], models=[], duration=30, chunks=[])
            with patch('ffbe_effects.ibmb.parse', return_value=effect):
                result = census.inspect_particle_files(root, ['hit.bmb'])['hit.bmb']
            self.assertTrue(result['parsed'])
            self.assertFalse(result['dependenciesComplete'])
            self.assertEqual(['missing.png'], result['missingDependencies'])
            self.assertNotIn('rendered', result)
            self.assertEqual(['hit.bmb'], [p.name for p in root.iterdir()])

    def test_unit_sprite_archive_is_not_an_effect_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root/'100.ffr', 'w') as archive:
                archive.writestr('native_kits/100.json', '{}')
                archive.writestr('sprites/100/idle.json', '{}')
            result = census.inspect_unit_archives(root, ['100', '101'])['forms']
            self.assertTrue(result['100']['exists'])
            self.assertTrue(result['100']['metadataReadable'])
            self.assertFalse(result['100']['preparedEffectsEmbedded'])
            self.assertFalse(result['101']['exists'])

    def test_full_census_keeps_memberships_distinct_moves_and_fidelity_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'data/ability_converter').mkdir(parents=True)
            (root/'data/ffbe/presentation').mkdir(parents=True)
            index = root/'index.json'
            index.write_text(json.dumps([{'id': '10', 'forms': ['100', '101']}]))
            database = sqlite3.connect(root/'data/ability_converter/vision-kits.sqlite')
            database.execute('CREATE TABLE kits(form TEXT,unit_id TEXT,payload BLOB)')
            database.execute('CREATE TABLE profiles(source_key TEXT,supported INTEGER,payload BLOB)')
            entries = [{'sourceKey': 'GL_2024/ability/1', 'kind': 'ABILITY', 'status': 'ready'},
                       {'sourceKey': 'GL_2024/passive/2', 'kind': 'PASSIVE', 'status': 'held'}]
            for form in ('100', '101'):
                database.execute('INSERT INTO kits VALUES(?,?,?)', (form, '10', zlib.compress(json.dumps({'entries': entries}).encode())))
            record = {'source': 'GL_2024', 'kind': 'ability', 'id': '1', 'data': {'effect_frames': []}}
            database.execute('INSERT INTO profiles VALUES(?,?,?)', ('GL_2024/ability/1', 1,
                             zlib.compress(json.dumps({'snapshot': {'records': [record]}}).encode())))
            database.commit(); database.close()
            tables = Tables({('GL_2024', 'F_ABILITY_MST'): {'1': {'effect_frames': ''}},
                             ('JP_CLIENT', 'F_ABILITY_MST'): {'1': {'effect_frames': ''}}})
            with patch.object(census, 'SourceTables', return_value=tables), \
                 patch.object(census, 'inspect_audio', return_value={'cues': {}}):
                report = census.build_census(root, catalog_path=index, unit_dir=root/'units', parse_particles=False)
            self.assertEqual(1, report['counts']['catalogUnits'])
            self.assertEqual(2, report['counts']['catalogForms'])
            self.assertEqual(2, report['memberships']['allActive'])
            self.assertEqual(1, report['counts']['distinctActiveMoves'])
            self.assertEqual(100, report['sourceCoverage']['sourceResolved']['readyMemberships']['percent'])
            self.assertEqual(0, report['renderedCoverage']['preparedMoveMemberships'])
            self.assertEqual('unmeasured by this census', report['renderedCoverage']['nativeVisualAccuracy'])
            self.assertEqual(0, report['bundleCoverage']['rawUnitArchivePresence']['numerator'])


if __name__ == '__main__':
    unittest.main()
