"""Local catalog routing, payload checks, and archive audit failure cases."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/devui'), str(ROOT / 'tools/private')]
import converted_units
import unit_downloads
from prepare_converted_catalog import audit_archive


class LocalConvertedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.delivery = self.root / 'delivery'; self.delivery.mkdir()
        self.file = self.delivery / '100.ffr'; self.file.write_bytes(b'prepared archive')
        self.info = {'size': self.file.stat().st_size, 'sha256': hashlib.sha256(self.file.read_bytes()).hexdigest(),
                     'localArchive': str(self.file), 'effects': 'ffr-effects-1'}
        self.base = self.root / 'index.json'
        self.base.write_text(json.dumps({'units': [{'id':'100','packs':['100','101']}],
            'unitBundles': {'100': {'url':'https://example.test/old.ffr'}, '101': {'url':'https://example.test/base.ffr'}}}))
        self.data = {'schema':'ffr-local-converted-units-1', 'baseline':str(self.base), 'delivery':str(self.delivery),
                     'summary':{'auditedExports':1}, 'unitBundles':{'100':self.info}}
        self.manifest = self.root / 'local.json'
        self.manifest.write_text(json.dumps(self.data))
        p = patch.dict('os.environ', FFR_CONVERTED_UNITS=str(self.manifest))
        p.start(); self.addCleanup(p.stop)
        converted_units._read.cache_clear()

    def test_local_catalog_keeps_fallbacks_and_never_exposes_disk_paths_to_client(self):
        result = converted_units.overlay({}, 'http://127.0.0.1:8765/')
        self.assertEqual(result['unitBundles']['100']['url'], 'http://127.0.0.1:8765/api/assets/converted/100')
        self.assertNotIn('localArchive', result['unitBundles']['100'])
        self.assertEqual(result['unitBundles']['101']['url'], 'https://example.test/base.ffr')
        self.assertEqual(converted_units.overlay({})['unitBundles']['100']['url'], self.file.as_uri())

    def test_source_file_is_hash_checked_without_a_network_request(self):
        info = {**self.info, 'url': self.file.as_uri()}
        target = self.root / 'cached.ffr'
        unit_downloads.download(info, target, lambda **kw: None)
        self.assertEqual(target.read_bytes(), self.file.read_bytes())

    def test_frozen_unit_catalog_uses_separate_shared_media_root(self):
        shared = self.root / 'shared'
        digest = 'a' * 64
        blob = shared / 'blobs/aa' / digest
        blob.parent.mkdir(parents=True)
        blob.write_bytes(b'immutable media')
        self.data['effectsDelivery'] = str(shared)
        self.data['unitBundles']['100']['effects'] = 'ffr-effects-ref-1'
        self.manifest.write_text(json.dumps(self.data))
        converted_units._read.cache_clear()
        info = converted_units.overlay({})['unitBundles']['100']
        self.assertEqual(info['effectBaseUrl'], shared.as_uri() + '/')
        self.assertEqual(converted_units.blob('aa', digest), blob)
        self.assertEqual(converted_units.archive('100'), self.file)

    def test_changed_file_and_unselected_or_escaping_paths_are_rejected(self):
        self.file.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'):
            converted_units.archive('100')
        with self.assertRaises(ValueError):
            converted_units.archive('../100')
        with self.assertRaises(FileNotFoundError):
            converted_units.archive('101')
        self.data['unitBundles']['100']['localArchive'] = str(self.root / 'elsewhere.ffr')
        self.manifest.write_text(json.dumps(self.data))
        converted_units._read.cache_clear()
        with self.assertRaisesRegex(ValueError, 'outside'):
            converted_units.archive('100')

    def test_base_only_form_does_not_count_as_a_broken_effect_archive(self):
        with zipfile.ZipFile(self.file, 'w') as z:
            z.writestr('sprites/100/unit_anime_100.png', b'fixture')
        base = {'size': self.file.stat().st_size, 'sha256':'a'*64, 'format':'ffr-unit-1'}
        info = audit_archive({'form':'100','operation':'preserve-base-unit'}, self.delivery, base)
        self.assertEqual(info['preparedMoveCount'], 0)


if __name__ == '__main__':
    unittest.main()
