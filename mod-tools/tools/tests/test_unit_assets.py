"""Unit bundles resolve without developer tables; split audio stays byte-identical."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/devui'), str(ROOT / 'tools/release')]
import ffbe_audio
import ffbe_audio_assets
import ffbe_categories
import ffbe_catalog as fc
import ffbe_lb
import ffbe_resonance
import unit_assets
from ffbe_effects import acb_native
from ffbe_effects.acb_cues import utf


class UnitAssetsTests(unittest.TestCase):
    def test_idle_pack_is_complete_and_changes_with_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            idle = root / 'ffbe/idle'; idle.mkdir(parents=True)
            forms = {}
            def add(form, data):
                (idle / (form + '.webp')).write_bytes(data)
                forms[form] = {'idle': {'sha256': hashlib.sha256(data).hexdigest()}}
            add('123', b'first')
            info = unit_assets.idle_pack(root, forms)
            self.assertEqual(info, unit_assets.idle_pack(root, forms))
            add('124', b'shift')
            newer = unit_assets.idle_pack(root, forms)
            self.assertNotEqual(info['sha256'], newer['sha256'])
            with zipfile.ZipFile(root / 'previews' / newer['url'].rsplit('/', 1)[-1]) as z:
                self.assertEqual(set(z.namelist()), {'123.webp', '124.webp'})
                self.assertEqual(z.read('124.webp'), b'shift')
            (idle / '124.webp').write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                unit_assets.idle_pack(root, forms)

    def test_shipped_shift_catalog_wins_over_partial_download_cache(self):
        # Reported units: base-only caches must not remove either BS option.
        units = [{'id': base, 'forms': [base, shift], 'pairOf': shift,
                  'shift': {shift: {'kind': 'brave_shift', 'base': base}}}
                 for base, shift in [('401013807', '401013817'), ('340000107', '340000117')]]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'pack'; data.mkdir()
            cache = root / 'cache'; cache.mkdir()
            (data / 'catalog.json').write_text(json.dumps({'units': units}))
            (cache / 'ffbe_index.json').write_text(json.dumps([{'id': u['id'], 'forms': [u['id']]} for u in units]))
            with patch.object(fc, 'PACK', str(data)), patch.object(fc, 'OUT', str(cache)), \
                 patch.object(fc, '_idx_rows', None), patch.object(fc, 'sprite_map', side_effect=AssertionError('Must not scan local sprites')):
                self.assertEqual(fc.load_index(), units)
                for u in units:
                    self.assertEqual(fc.shift_info(u['pairOf'])['base'], u['id'])

    def test_negative_ffbe_cue_gets_preroll_without_shifting_relative_hits(self):
        sound = {'frame': -89, 'durationMs': 1000, 'bank': 'test', 'cueName': 'charge'}
        plan = ffbe_resonance.schedule(2., 1, 444010, {'hitFrames': [60]}, [sound])
        events = plan['events']
        sound_time = next(e['time'] for e in events if e['set']['EventType'] == 'SoundPlayHitSound')
        hit_time = next(e['time'] for e in events if e['set']['EventType'] == 'OtherReaction')
        self.assertGreaterEqual(sound_time, 0)
        self.assertEqual(hit_time - sound_time, 149 * (ffbe_resonance.TICKS // 60))

    def test_archive_content_is_stable_and_tracks_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '123.ffr'
            first = unit_assets.archive(path, {'unit.json': b'{}', 'idle.csv': b'0'})
            second = unit_assets.archive(path, {'idle.csv': b'0', 'unit.json': b'{}'})
            self.assertEqual(first, second)
            self.assertNotEqual(first, unit_assets.archive(path, {'unit.json': b'{"new":true}'}))

    def test_categories_merge_forms_and_fill_series_on_old_records(self):
        units = [{'id': '1', 'forms': ['11'], 'mergedIds': ['2']}]
        sources = {'GL': {'units': {'1': {'game_id': 10006}, '2': {'tags': [10000001]}}}}
        ffbe_categories.enrich(units, sources, [{'unit_evo_id': '11', 'tags': '20000002'}])
        self.assertEqual(set(units[0]['categories']), {'30010006', '10000001', '20000002'})

    def test_compact_catalog_and_lb_variants_need_no_full_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); data = root / 'data/ffbe'
            (data / 'unit_records').mkdir(parents=True)
            (data / 'lb_profiles').mkdir()
            (data / 'catalog.json').write_text('{"units": []}')
            record = {'detail': {'id': '1', 'name': 'Test', 'forms': {}},
                      'sources': {'JP': {'units': {'1': {'name': 'Test'}}, 'skills_ability': {'9': {'name': 'Slash'}}}}}
            (data / 'unit_records/1.json').write_text(json.dumps(record))
            doc = {'schema': 1, 'form': '11', 'regions': {'JP': {'22': {'source': {'name': 'First'}}, '23': {'source': {'name': 'Second'}}}}}
            (data / 'lb_profiles/11.json').write_text(json.dumps(doc))
            with patch.object(fc, 'PACK', str(data)), patch.object(fc, '_src', None), \
                 patch.object(ffbe_lb, 'ROOT', root), patch.object(ffbe_lb, 'table', side_effect=AssertionError('Must use unit bundle')):
                self.assertEqual(fc.unit_detail('1')['name'], 'Test')
                self.assertEqual(fc.sources()['JP']['skills_ability']['9']['name'], 'Slash')
                self.assertEqual(ffbe_lb.resolve({'ffbe': {'id': '11', 'source': 'JP'}}, {'ffbe_lb_id': '23'})['name'], 'Second')
                with self.assertRaises(ValueError):
                    ffbe_lb.resolve({'ffbe': {'id': '11', 'source': 'JP'}}, {'ffbe_lb_id': '99'})

    def test_split_recordings_build_exact_native_bank_bytes(self):
        original = Path('S:/FFBE JP Data Export/public/SE.acb')
        host_path = ROOT / 'extracted/legacy' / (ffbe_audio.SHELL + '.uexp')
        if not original.exists() or not host_path.exists():
            self.skipTest('Requires local source and native audio banks')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = unit_assets.AudioLibrary('SE', root / 'audio/samples')
            doc = library.selection([1, 4, 181, 647])
            path = root / 'audio/lb/123.json'; path.parent.mkdir()
            path.write_bytes(unit_assets.encoded(doc))
            host = host_path.read_bytes(); host = host[host.index(b'@UTF'):]
            host = host[:int.from_bytes(host[4:8], 'big') + 8]
            records, omitted = ffbe_audio.native_selection(str(path), path.stat().st_mtime_ns, (1, 4, 181, 647), True)
            self.assertFalse(omitted)
            self.assertEqual(records, doc['recordings'])
            raw_waves = ffbe_audio_assets.waves(path, doc)
            for key, raw in raw_waves.items():
                self.assertEqual(hashlib.sha256(raw).hexdigest(), doc['waves'][str(key)]['sha256'])
            legacy = acb_native.build(original.read_bytes(), host, 'SameBank', records)
            split = acb_native.build(b'', host, 'SameBank', records, raw_waves=raw_waves)
            self.assertEqual(legacy, split)
            self.assertTrue(utf(split)[1][0]['AwbFile'])
