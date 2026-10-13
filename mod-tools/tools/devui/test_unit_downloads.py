import hashlib
import http.server
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'tests')]
import unit_downloads as assets
import ffbe_effect_bundle as effects
from test_ffbe_effect_bundle import fixture


class Downloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name) / 'engine'
        self.root.mkdir()
        self.requested = []
        self.files = {}
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                owner.requested.append(self.path)
                data = owner.files.get(self.path)
                self.send_response(200 if data is not None else 404); self.end_headers()
                if data is not None: self.wfile.write(data)
        self.http = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = f'http://127.0.0.1:{self.http.server_port}/'
        self.root_patch = patch.object(assets, 'ROOT', self.root); self.root_patch.start()
        self.refresh = patch('ffbe_catalog.build_index'); self.refresh.start()

    def tearDown(self):
        self.refresh.stop(); self.root_patch.stop(); self.http.shutdown(); self.http.server_close(); self.tmp.cleanup()

    def info(self, name, content):
        self.files['/' + name] = content
        return {'url': self.base + name, 'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}

    def bundle(self, form, extra=None):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            for name in [f'sprites/{form}/unit_anime_{form}.png', f'sprites/{form}/unit_cgg_{form}.csv', f'sprites/{form}/unit_idle_cgs_{form}.csv', 'unit_records/100.json', f'lb_profiles/{form}.json', f'audio/lb/{form}.json']:
                z.writestr(name, '{}')
            if extra: z.writestr(extra, 'escape')
        return {**self.info(form + '.ffr', out.getvalue()), 'format': 'ffr-unit-1', 'unitId': '100', 'sounds': [self.info('shared.hca', b'audio sample')]}

    def test_shift_fetches_base_and_reuses_shared_audio_and_complete_packs(self):
        cat = {'units': [{'id': '100', 'packs': ['100', '101'], 'shift': {'101': {'base': '100'}}}],
               'unitBundles': {'100': self.bundle('100'), '101': self.bundle('101')}}
        (self.root.parent / 'ffbe_index_cache.json').write_text(json.dumps(cat))
        assets.ensure_selection('100', '101')
        self.assertEqual(['/101.ffr', '/shared.hca', '/100.ffr'], self.requested)
        assets.ensure_selection('100', '101')
        self.assertEqual(3, len(self.requested))
        self.assertTrue((self.root / 'data/ffbe/sprites/100/.complete').exists())
        with self.assertRaises(ValueError): assets.ensure_selection('100', '999')

    def test_archive_traversal_is_rejected_before_merge(self):
        info = self.bundle('100', '../../escape.txt')
        with self.assertRaisesRegex(ValueError, 'unsafe filename'):
            assets.ensure_form('100', info, lambda **kw: None)
        self.assertFalse((self.root / 'data/ffbe/sprites/100').exists())
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_shared_shift_downloads_only_the_selected_limit_burst(self):
        cat = {'units': [{'id': '100', 'packs': ['100', '101'], 'shift': {'101': {'base': '100'}}}],
               'unitBundles': {fid: {'effects': 'ffr-effects-ref-1'} for fid in ('100', '101')}}
        native = self.root/'data/ffbe/native_kits/101.json'
        native.parent.mkdir(parents=True)
        native.write_text(json.dumps({'kit': {'entries': [{'kind': 'LB', 'status': 'ready', 'sourceKey': 'shift-lb'}]}}))
        with patch.object(assets, 'index', return_value=cat), patch.object(assets, 'ensure_form') as form, \
             patch('ffbe_effect_refs.read_installed', return_value=({}, {'moves': {'shift-lb': {}}})), \
             patch('effect_downloads.ensure_move') as move:
            assets.ensure_selection('100', '101')
        self.assertEqual([c.args[0] for c in form.call_args_list], ['101', '100'])
        self.assertEqual([c.args[:2] for c in move.call_args_list], [('101', 'shift-lb')])

    def test_presentation_manifest_is_required_and_extracted(self):
        info = {**self.bundle('100', 'presentation/100.json'), 'presentation':'ffr-presentation-1'}
        assets.ensure_form('100', info, lambda **kw: None)
        self.assertTrue((self.root/'data/ffbe/presentation/100.json').is_file())
        missing = {**self.bundle('101'), 'presentation':'ffr-presentation-1'}
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            assets.ensure_form('101', missing, lambda **kw: None)

    def prepared_bundle(self, *, compress_textures=False):
        presentation = fixture(self.root, '100')
        artifact = self.root / 'effects.ffr'
        effects.pack(presentation, artifact, root=self.root, compress_textures=compress_textures)
        base = self.bundle('100')
        unit = self.root / 'unit.ffr'
        unit.write_bytes(self.files['/100.ffr'])
        merged = self.root / 'merged.ffr'
        meta = effects.merge(unit, artifact, merged)
        return {**base, **meta, **self.info('100.ffr', merged.read_bytes()), 'sounds': []}

    def test_prepared_effects_import_repairs_missing_and_changed_dependencies(self):
        info = self.prepared_bundle()
        assets.ensure_form('100', info, lambda **kw: None)
        texture = self.root / 'data/ffbe/presentation/assets/FFBE_FX_test/tex.bgra'
        texture.unlink()
        assets.ensure_form('100', info, lambda **kw: None)
        self.assertEqual(b'\0' * 16, texture.read_bytes())
        texture.write_bytes(b'\1' * 16)
        assets.ensure_form('100', info, lambda **kw: None)
        self.assertEqual(b'\0' * 16, texture.read_bytes())
        self.assertEqual(['/100.ffr'], self.requested)

    def test_compressed_prepared_import_repairs_encoded_page_without_expanding_installed_data(self):
        info=self.prepared_bundle(compress_textures=True)
        (self.root/'data/ffbe/presentation/assets/FFBE_FX_test/tex.bgra').unlink()
        assets.ensure_form('100',info,lambda **kw:None)
        project=self.root/'data/ffbe/presentation/assets/FFBE_FX_test'
        spec=json.loads((project/'spec.json').read_text())
        texture=project/spec['textureFile']
        expected=texture.read_bytes()
        self.assertEqual(spec['textureEncoding'],'zlib')
        self.assertEqual(effects.decode_texture(spec,expected),b'\0'*16)
        for broken in (None,b'invalid encoded page'):
            if broken is None:texture.unlink()
            else:texture.write_bytes(broken)
            assets.ensure_form('100',info,lambda **kw:None)
            self.assertEqual(texture.read_bytes(),expected)
        self.assertEqual(['/100.ffr'],self.requested)
        self.assertFalse((project/'tex.bgra').exists())
        effects.verify_installed(self.root/'data/ffbe','100')

    def test_invalid_prepared_dependency_is_rejected_before_replacing_installed_files(self):
        info = self.prepared_bundle()
        archive = self.root / 'bad.ffr'
        files = effects.read_archive(self.root / 'merged.ffr')
        files['presentation/assets/FFBE_FX_test/tex.bgra'] = b'\2' * 16
        effects._write_archive(archive, files)
        info.update(self.info('bad.ffr', archive.read_bytes()))
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            assets.ensure_form('100', info, lambda **kw: None)
        self.assertFalse((self.root / 'data/ffbe/sprites/100').exists())


if __name__ == '__main__': unittest.main()
