"""Exercise the publisher and the same lazy importer used by desktop Studio."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

TOOLS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TOOLS), str(TOOLS / 'devui'), str(TOOLS / 'tests')]
import ffbe_effect_bundle as old
import ffbe_effect_refs as refs
from ffbe_effects.shared_delivery import Publisher, recover_raw_spec
from ffbe_effects import regional_assets
from test_ffbe_effect_bundle import fixture
import unit_downloads
import effect_downloads


class SharedEffects(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = fixture(self.root)
        self.doc = json.loads(self.manifest.read_bytes())
        self.key = next(iter(self.doc['moves']))
        self.snapshot = {'records': [{'source': 'GL', 'kind': 'ability', 'id': '7', 'data': {}}]}
        fingerprint = old._sha(json.dumps([{k: r.get(k) for k in ('source', 'kind', 'id', 'level', 'data')}
                                          for r in self.snapshot['records']], sort_keys=True, ensure_ascii=False).encode())
        self.doc['moves'][self.key]['sourceSha256'] = fingerprint
        self.delivery = self.root / 'delivery'
        self.publisher = Publisher(self.root, self.delivery)
        self.base = self.root / 'base.ffr'
        files = {f'sprites/123/unit_{kind}_123.{ext}': b'fixture' for kind, ext in [('anime','png'), ('cgg','csv'), ('idle_cgs','csv')]}
        files.update({'unit_records/12.json': b'{}', 'lb_profiles/123.json': b'{}', 'audio/lb/123.json': b'{}',
                      'native_kits/123.json': old.encoded({'profiles': {self.key: {'snapshot': self.snapshot}}})})
        old._write_archive(self.base, files)

    def pack(self):
        return self.publisher.pack(self.doc, self.base, self.delivery / '123.ffr', {'missingMoveCount': 0})

    def test_small_unit_references_deduplicated_lossless_files(self):
        info = self.pack()
        files = old.read_archive(self.delivery / '123.ffr')
        index = refs.verify_thin(files, '123')
        self.assertFalse(any(n.endswith('.bgra.z') for n in files))
        presentation = old._json(files['presentation/123.json'])
        read = lambda n: refs.decode(index['files'][n], (self.delivery / refs.blob_name(index['files'][n]['sha256'])).read_bytes())
        refs.verify_move(index, presentation, self.key, read)
        blobs_before = list(self.delivery.glob('blobs/*/*'))
        self.assertEqual(info, self.pack())
        self.assertEqual(blobs_before, list(self.delivery.glob('blobs/*/*')))
        visual = presentation['moves'][self.key]['visuals'][0]
        spec = old._json(read(visual['spec'][len('data/ffbe/'):] + '/spec.json'))
        self.assertEqual(b'\0' * 16, old.decode_texture(spec, read(visual['spec'][len('data/ffbe/'):] + '/tex.bgra.z')))

    def test_beta_snapshot_survives_replacement_of_the_live_unit_file(self):
        sys.path.insert(0, str(TOOLS/'release'))
        from build_local_beta import snapshot
        info = {**self.pack(), 'unitId': '12', 'withinThreshold': True, 'missingMoveCount': 0,
                'localArchive': str(self.delivery/'123.ffr')}
        baseline = self.root/'baseline.json'
        baseline.write_bytes(old.encoded({'units': [], 'unitBundles': {'123': {'unitId': '12'}}}))
        live = self.root/'live.json'
        live.write_bytes(old.encoded({'delivery': str(self.delivery), 'baseline': str(baseline), 'unitBundles': {'123': info}}))
        frozen = snapshot(self.root/'beta', live)
        target = Path(frozen['unitBundles']['123']['localArchive'])
        expected = target.read_bytes()
        (self.delivery/'123.ffr').write_bytes(b'new live archive')
        self.assertEqual(target.read_bytes(), expected)
        self.assertEqual(frozen['effectsDelivery'], str(self.delivery.resolve()))
        self.assertEqual(frozen['summary']['bundledForms'], 1)
        self.assertEqual(snapshot(self.root/'beta', live), frozen)

    def test_legacy_portable_overwrite_recovers_only_the_exact_original(self):
        spec = {'pixelSize': [2.0, 2.0], 'cells': [], 'model': {'parts': [{'name': 'root', 'parent': -1,
            'type': 'Null', 'blend': 'Mix', 'inherit': 'Self'}]}, 'animations': [], 'cellmapName': 'test',
            'animePackName': 'test', 'imagePath': 'test.png', 'runtimeScale': 1.0}
        raw = json.dumps(spec, ensure_ascii=False, separators=(',', ':')).encode()
        portable = {**spec, 'textureEncoding': 'zlib', 'textureFile': 'tex.bgra.z', 'textureBytes': 16,
                    'textureSha256': old._sha(b'\0' * 16)}
        self.assertEqual(raw, recover_raw_spec(old.encoded(portable), old._sha(raw)))
        portable['runtimeScale'] = 2.0
        self.assertIsNone(recover_raw_spec(old.encoded(portable), old._sha(raw)))

    def test_import_does_not_fetch_effects_until_equipped_and_repairs_damage(self):
        info = {**self.pack(), 'unitId': '12', 'url': (self.delivery / '123.ffr').as_uri(),
                'effectBaseUrl': self.delivery.as_uri() + '/'}
        consumer = self.root / 'consumer'
        with patch.object(unit_downloads, 'ROOT', consumer), patch.object(unit_downloads, 'app_root', return_value=consumer/'cache'), \
             patch.object(unit_downloads, 'index', return_value={'unitBundles': {'123': info}}):
            unit_downloads.ensure_form('123', info, lambda **kw: None)
            data = consumer / 'data/ffbe'
            self.assertFalse((data/'presentation/assets').exists())
            self.assertTrue(effect_downloads.ensure_move('123', self.key))
            index, presentation = refs.read_installed(data, '123')
            refs.verify_move(index, presentation, self.key, lambda n: (data/n).read_bytes())
            import ffbe_audio_assets
            bank = data / presentation['moves'][self.key]['audioBank'].removeprefix('data/ffbe/')
            self.assertEqual({1: b'prepared recording'}, ffbe_audio_assets.waves(bank, ffbe_audio_assets.read(bank)))
            texture = next(data.glob('presentation/assets/shared/*/*.bgra.z'))
            texture.write_bytes(b'broken')
            self.assertTrue(effect_downloads.ensure_move('123', self.key))
            refs.verify_move(index, presentation, self.key, lambda n: (data/n).read_bytes())
            self.assertFalse(effect_downloads.ensure_move('123', 'GL/ability/missing'))

    def test_index_cannot_hide_extra_files_or_cross_form_paths(self):
        self.pack()
        files = old.read_archive(self.delivery / '123.ffr')
        index = old._json(files['presentation/effects/123.json'])
        presentation = old._json(files['presentation/123.json'])
        with self.assertRaises(ValueError): refs.validate(index, presentation, '124')
        bad = deepcopy(index)
        bad['files']['../../outside'] = next(iter(index['files'].values()))
        with self.assertRaises(ValueError): refs.validate(bad, presentation, '123')
        bad = deepcopy(index)
        bad['moves'][self.key] = []
        with self.assertRaises(ValueError): refs.validate(bad, presentation, '123')

    def test_bounded_decompression_and_corruption_are_rejected(self):
        data = zlib.compress(b'a' * 1000)
        info = {'sha256': old._sha(data), 'size': len(data), 'decodedSha256': old._sha(b'a'), 'decodedSize': 1, 'encoding': 'zlib'}
        with self.assertRaises(ValueError): refs.decode(info, data)
        with self.assertRaises(ValueError): refs.decode(info, b'broken')

    def test_threshold_counts_held_active_moves_as_missing(self):
        from recover_ffbe_animations import coverage
        active = [{'sourceKey': str(i), 'status': 'ready' if i < 4 else 'held'} for i in range(5)]
        report = coverage(active, {'0': {}, '1': {}}, [], 3)
        self.assertTrue(report['withinThreshold'])
        self.assertEqual(3, report['missingMoveCount'])
        self.assertEqual(1, report['heldMoveCount'])
        self.assertFalse(coverage(active, {'0': {}}, [], 3)['withinThreshold'])
        self.assertFalse(coverage(active[:1], {}, [], 3)['withinThreshold'])
        self.assertTrue(coverage([], {}, [], 3)['withinThreshold'])

    def test_negative_preroll_preserves_spacing_and_cast_clock(self):
        sys.path.insert(0, str(TOOLS/'ffbe_effects'))
        from prepare_vision import normalize_preroll
        timeline = {'spawns': [{'frame': -54, 'sourceGroupFrame': -55}, {'frame': 20, 'sourceGroupFrame': 15},
                               {'phase': 'cast', 'frame': 1}], 'sounds': [{'frame': -50}], 'issues': []}
        normalize_preroll(timeline)
        self.assertEqual([1, 75, 1], [s['frame'] for s in timeline['spawns']])
        self.assertEqual(5, timeline['sounds'][0]['frame'])
        self.assertEqual(55, timeline['sourcePrerollFrames'])
        self.assertEqual(-55, timeline['spawns'][0]['sourceSignedGroupFrame'])

    def test_conflicting_common_revision_is_not_resolved_arbitrarily(self):
        paths = []
        for directory, content in [('Ver25_effectResource3_common','battle'), ('Ver4_effectResource1_common_tutorial','tutorial'), ('Ver13_effectResource1_common','old')]:
            path = self.root / directory / 'texture.png'
            path.parent.mkdir(); path.write_text(content); paths.append(path)
        chosen, reason = regional_assets.choose('texture.png', {'texture.png': paths}, self.root)
        self.assertEqual(paths[0], chosen)
        self.assertIn('export policy', reason)
        other = self.root / 'different/Ver25_effectResource3_common/texture.png'
        other.parent.mkdir(parents=True); other.write_text('conflicting newest')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            regional_assets.choose('texture.png', {'texture.png': paths+[other]}, self.root)


if __name__ == '__main__': unittest.main()
