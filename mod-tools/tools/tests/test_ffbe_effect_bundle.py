import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

TOOLS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TOOLS), str(TOOLS / 'release')]
import ffbe_effect_bundle as effects
import build_release


def fixture(root, form='123'):
    data = root / 'data/ffbe'
    def put(name, raw):
        path = data / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()
    project = 'presentation/assets/FFBE_FX_test'
    texture = b'\0' * 16
    spec = effects.encoded({'pixelSize': [2.0, 2.0]})
    hashes = {'spec.json': put(project + '/spec.json', spec), 'tex.bgra': put(project + '/tex.bgra', texture)}
    wave = b'prepared recording'
    digest = hashlib.sha256(wave).hexdigest()
    put('audio/samples/' + digest + '.hca', wave)
    bank = {'schema': 'ffr-audio-1', 'waves': {'1': {'sha256': digest, 'size': len(wave)}}}
    put('audio/presentation_test.json', effects.encoded(bank))
    move = {'sourceKey': 'GL/ability/7', 'sourceSha256': '7' * 64, 'status': 'partial', 'issues': ['3D projection requires review'],
            'audioBank': 'data/ffbe/audio/presentation_test.json', 'sounds': [{'frame': 12, 'cueId': 1}],
            'visuals': [{'spec': 'data/ffbe/' + project, 'checksums': hashes}]}
    presentation = {'schema': 'ffr-presentation-2', 'form': form, 'moves': {move['sourceKey']: move}}
    put(f'presentation/{form}.json', effects.encoded(presentation))
    return data / f'presentation/{form}.json'


class EffectsBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.presentation = fixture(self.root)
        self.artifact = self.root / '123.ffr'

    def tearDown(self):
        self.tmp.cleanup()

    def pack(self):
        return effects.pack(self.presentation, self.artifact, root=self.root, compress_textures=False,
                            reports={'validation.json': {'nativePlayback': 'not_run'}})

    def test_secondary_system_bank_and_samples_survive_portable_pack(self):
        document=json.loads(self.presentation.read_bytes())
        move=next(iter(document['moves'].values()))
        raw=b'prepared System cue distinct from SE'
        digest=hashlib.sha256(raw).hexdigest()
        sample=self.root/'data/ffbe/audio/samples'/(digest+'.hca')
        sample.write_bytes(raw)
        bank=self.root/'data/ffbe/audio/system.json'
        bank.write_bytes(effects.encoded({'schema':'ffr-audio-1','waves':{'95':{'sha256':digest,'size':len(raw)}}}))
        move['audioBanks']={'SE':move['audioBank'],'System':'data/ffbe/audio/system.json'}
        move['sounds'].append({'frame':20,'cueId':95,'sourceBank':'System'})
        self.presentation.write_bytes(effects.encoded(document))
        self.pack()
        files=effects.read_archive(self.artifact)
        self.assertEqual(files['audio/samples/'+digest+'.hca'],raw)
        self.assertIn('audio/system.json',files)
        effects.verify(self.artifact,'123')
        sample.write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'checksum'): self.pack()

    def test_deterministic_archive_retains_reports_and_every_dependency(self):
        first = self.pack()
        raw = self.artifact.read_bytes()
        self.assertEqual(first, self.pack())
        self.assertEqual(raw, self.artifact.read_bytes())
        manifest = effects.verify(self.artifact, '123')
        self.assertEqual('ffr-effects-1', first['format'])
        self.assertEqual('partial', manifest['moves']['GL/ability/7']['status'])
        self.assertEqual(['3D projection requires review'], manifest['moves']['GL/ability/7']['issues'])
        self.assertEqual(['presentation/reports/123/validation.json'], manifest['reports'])
        self.assertEqual(5, len(manifest['files']) - len(manifest['reports']))

    def test_changed_texture_cannot_replace_an_existing_artifact(self):
        self.pack()
        before = self.artifact.read_bytes()
        (self.root / 'data/ffbe/presentation/assets/FFBE_FX_test/tex.bgra').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            self.pack()
        self.assertEqual(before, self.artifact.read_bytes())

    def test_missing_dependency_and_wrong_form_are_rejected(self):
        self.pack()
        with self.assertRaisesRegex(ValueError, 'different unit form'):
            effects.verify(self.artifact, '124')
        files = effects.read_archive(self.artifact)
        del files['presentation/assets/FFBE_FX_test/tex.bgra']
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            effects.verify_files(files, standalone=True)

    def test_content_index_cannot_hide_unindexed_or_retargeted_source_paths(self):
        doc = json.loads(self.presentation.read_text())
        doc['moves']['GL/ability/7']['visuals'][0]['spec'] = 'data/ffbe/presentation/assets/../../escape'
        self.presentation.write_bytes(effects.encoded(doc))
        with self.assertRaisesRegex(ValueError, 'unsafe filename'):
            self.pack()
        self.assertFalse(self.artifact.exists())

    def test_texture_dimensions_are_enforced_even_when_hash_matches(self):
        spec = self.root / 'data/ffbe/presentation/assets/FFBE_FX_test/spec.json'
        spec.write_bytes(effects.encoded({'pixelSize': [4, 4]}))
        doc = json.loads(self.presentation.read_text())
        doc['moves']['GL/ability/7']['visuals'][0]['checksums']['spec.json'] = hashlib.sha256(spec.read_bytes()).hexdigest()
        self.presentation.write_bytes(effects.encoded(doc))
        with self.assertRaisesRegex(ValueError, 'size mismatch'):
            self.pack()

    def test_unsafe_duplicate_and_symlink_zip_entries_are_rejected(self):
        for names in [['../escape'], ['A.json', 'a.json'], ['thing', 'thing/child'], ['NUL.json'], ['a\\b']]:
            with self.subTest(names=names):
                stream = io.BytesIO()
                with zipfile.ZipFile(stream, 'w') as archive:
                    for name in names:
                        entry = zipfile.ZipInfo('placeholder')
                        entry.filename = name  # Avoid Windows ZipInfo normalizing backslashes in the fixture.
                        archive.writestr(entry, b'{}')
                with self.assertRaises(ValueError):
                    effects.read_archive(io.BytesIO(stream.getvalue()))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            entry = zipfile.ZipInfo('link'); entry.create_system = 3; entry.external_attr = 0o120777 << 16
            archive.writestr(entry, b'elsewhere')
        with self.assertRaisesRegex(ValueError, 'unsupported entry'):
            effects.read_archive(io.BytesIO(stream.getvalue()))

    def test_unknown_payload_and_missing_dependency_index_are_rejected(self):
        self.pack()
        files = effects.read_archive(self.artifact)
        files['presentation/decoder.py'] = b'no source code'
        with self.assertRaisesRegex(ValueError, 'Unexpected file'):
            effects.verify_files(files, standalone=True)
        del files['presentation/decoder.py']
        name = 'presentation/effects/123.json'
        manifest = json.loads(files[name])
        del manifest['files']['audio/presentation_test.json']
        files[name] = effects.encoded(manifest)
        with self.assertRaisesRegex(ValueError, 'content index'):
            effects.verify_files(files, standalone=True)

    def test_merge_preserves_unit_payload_and_is_deterministic(self):
        self.pack()
        unit = self.root / 'unit.ffr'
        original = {'sprites/123/unit_anime_123.png': b'sprite', 'lb_profiles/123.json': b'{}', 'unit_records/12.json': b'{}'}
        effects._write_archive(unit, original)
        merged = self.root / 'unit-effects.ffr'
        info = effects.merge(unit, self.artifact, merged)
        payload = effects.read_archive(merged)
        self.assertEqual(original, {n: payload[n] for n in original})
        effects.verify_files(payload, '123')
        self.assertEqual('ffr-unit-1', info['format'])
        self.assertEqual('ffr-effects-1', info['effects'])
        self.assertEqual(info, effects.merge(merged, self.artifact, merged))
        wrong = {n.replace('123', '124'): v for n, v in original.items()}
        effects._write_archive(unit, wrong)
        with self.assertRaisesRegex(ValueError, 'different unit archive'):
            effects.merge(unit, self.artifact, merged)

    def test_installed_dependencies_cannot_be_hidden_by_a_complete_marker(self):
        self.pack()
        files = effects.read_archive(self.artifact)
        for name, raw in files.items():
            path = self.root / 'installed' / name
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        effects.verify_installed(self.root / 'installed', '123')
        (self.root / 'installed/presentation/assets/FFBE_FX_test/tex.bgra').write_bytes(b'\1' * 16)
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            effects.verify_installed(self.root / 'installed', '123')

    def test_same_form_with_an_old_native_kit_cannot_accept_new_source_effects(self):
        self.pack()
        unit = self.root / 'unit.ffr'
        files = {'sprites/123/unit_anime_123.png': b'sprite', 'lb_profiles/123.json': b'{}', 'unit_records/12.json': b'{}',
                 'native_kits/123.json': effects.encoded({'profiles': {'GL/ability/7': {'snapshot': {'records': []}}}})}
        effects._write_archive(unit, files)
        with self.assertRaisesRegex(ValueError, 'Unit kit source differs'):
            effects.merge(unit, self.artifact, self.root / 'merged.ffr')

    def test_new_artifact_budget_is_bounded_before_write(self):
        with patch.object(effects, 'MAX_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'unpacking budget'):
                self.pack()
        self.assertFalse(self.artifact.exists())


class CompressedTextures(unittest.TestCase):
    def test_shared_pixels_compress_once_and_keep_complete_archive_bytes_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); source=fixture(root)
            doc=json.loads(source.read_bytes())
            visuals=doc['moves']['GL/ability/7']['visuals']
            original=root/visuals[0]['spec']
            # Different dimensions/metadata intentionally share the same pixel
            # bytes; compression may be shared, project metadata may not.
            other=original.with_name('FFBE_FX_other')
            other.mkdir()
            (other/'tex.bgra').write_bytes((original/'tex.bgra').read_bytes())
            (other/'spec.json').write_bytes(effects.encoded({'pixelSize':[1,4],'runtimeScale':.8}))
            visuals.append({'spec':other.relative_to(root).as_posix(),'checksums':{
                name:hashlib.sha256((other/name).read_bytes()).hexdigest() for name in ('spec.json','tex.bgra')}})
            source.write_bytes(effects.encoded(doc))
            before={p:p.read_bytes() for p in (root/'data').rglob('*') if p.is_file()}
            baseline=root/'unmemoized.ffr-effects'
            # The previous algorithm independently used zlib level 9 for every
            # validated page. Use it as an oracle for the entire archive.
            def independently_compress(raw,cache):
                return hashlib.sha256(raw).hexdigest(),zlib.compress(raw,level=9)
            with patch.object(effects,'_compress_page',side_effect=independently_compress):
                baseline_info=effects.pack(source,baseline,root=root)
            actual=root/'memoized.ffr-effects'
            saved=[]
            original_writer=effects._write_archive
            def inspect_files(path,files):
                saved.append([raw for name,raw in files.items() if name.endswith('.bgra.z')])
                return original_writer(path,files)
            with patch.object(effects.zlib,'compress',wraps=zlib.compress) as compress,\
                    patch.object(effects,'_write_archive',side_effect=inspect_files):
                actual_info=effects.pack(source,actual,root=root)
            self.assertEqual(compress.call_count,1)
            self.assertEqual(actual_info,baseline_info)
            self.assertEqual(actual.read_bytes(),baseline.read_bytes())
            self.assertEqual(len(saved[0]),2)
            self.assertIs(saved[0][0],saved[0][1])
            self.assertEqual(before,{p:p.read_bytes() for p in before})
            # Cache lifetime is one call; subsequent calls validate and compress
            # anew instead of retaining unbounded bytes across the catalog.
            with patch.object(effects.zlib,'compress',wraps=zlib.compress) as compress:
                effects.pack(source,actual,root=root)
            self.assertEqual(compress.call_count,1)
            (other/'tex.bgra').write_bytes(b'corrupt shared page')
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                effects.pack(source,actual,root=root)
            self.assertEqual(actual.read_bytes(),baseline.read_bytes())

    def test_multipage_specs_keep_pixel_identity_and_can_be_repacked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=fixture(root)
            project=source.parent/'assets/FFBE_FX_test'
            pages=[{'pixelSize':[2,2],'cells':[{'name':'first'}]},
                   {'pixelSize':[1,2],'textureFile':'tex_1.bgra','cells':[{'name':'second'}]}]
            original_spec={**pages[0],'cellmaps':pages,'model':{'name':'unchanged'},'runtimeScale':.8}
            (project/'spec.json').write_bytes(effects.encoded(original_spec))
            (project/'tex_1.bgra').write_bytes(bytes(range(8)))
            doc=json.loads(source.read_text())
            doc['moves']['GL/ability/7']['visuals'][0]['checksums']={
                name:hashlib.sha256((project/name).read_bytes()).hexdigest()
                for name in ('spec.json','tex.bgra','tex_1.bgra')}
            source.write_bytes(effects.encoded(doc))
            output=root/'original.ffr-effects'
            effects.pack(source,output,root=root)
            files=effects.read_archive(output)
            spec=json.loads(files['presentation/assets/FFBE_FX_test/spec.json'])
            self.assertEqual(spec['model'],original_spec['model'])
            self.assertEqual(spec['runtimeScale'],.8)
            self.assertEqual(spec['textureFile'],'tex.bgra.z')
            for page,expected in zip(spec['cellmaps'],(b'\0'*16,bytes(range(8)))):
                self.assertEqual(effects.decode_texture(page,files['presentation/assets/FFBE_FX_test/'+page['textureFile']]),expected)
            copied=root/'portable/data/ffbe'
            for name,raw in files.items():
                path=copied/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            repacked=root/'repacked.ffr-effects'
            effects.pack(copied/'presentation/123.json',repacked,root=root/'portable')
            self.assertEqual(output.read_bytes(),repacked.read_bytes())

    def test_default_pack_is_lossless_deterministic_and_does_not_change_source_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = fixture(root)
            originals = {p: p.read_bytes() for p in (root/'data').rglob('*') if p.is_file()}
            output = root/'compressed.ffr-effects'
            first = effects.pack(source, output, root=root)
            archive_bytes = output.read_bytes()
            self.assertEqual(first, effects.pack(source, output, root=root))
            self.assertEqual(output.read_bytes(), archive_bytes)
            self.assertEqual(originals, {p: p.read_bytes() for p in originals})
            files = effects.read_archive(output)
            manifest = effects.verify_files(files, '123', standalone=True)
            presentation = json.loads(files[manifest['presentation']])
            visual = presentation['moves']['GL/ability/7']['visuals'][0]
            self.assertEqual(presentation['moves']['GL/ability/7']['sourceSha256'], '7'*64)
            self.assertEqual(presentation['moves']['GL/ability/7']['issues'], ['3D projection requires review'])
            project = visual['spec'].removeprefix('data/ffbe/')
            spec = json.loads(files[project+'/spec.json'])
            self.assertEqual(spec['textureEncoding'], 'zlib')
            self.assertEqual(spec['textureBytes'], 16)
            self.assertEqual(spec['textureSha256'], hashlib.sha256(b'\0'*16).hexdigest())
            self.assertEqual(effects.decode_texture(spec, files[project+'/'+spec['textureFile']]), b'\0'*16)
            self.assertNotIn(project+'/tex.bgra', files)
            self.assertEqual(set(visual['checksums']), {'spec.json', 'tex.bgra.z'})
            self.assertEqual(first['textureCompression']['pages'], 1)
            self.assertEqual(first['textureCompression']['decodedBytes'], 16)

    def test_encoded_archive_budget_can_be_smaller_than_the_lossless_page_union(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = fixture(root)
            project = source.parent/'assets/FFBE_FX_test'
            raw = b'\0'*(128*128*4)
            (project/'tex.bgra').write_bytes(raw)
            (project/'spec.json').write_bytes(effects.encoded({'pixelSize':[128,128]}))
            doc = json.loads(source.read_text())
            visual = doc['moves']['GL/ability/7']['visuals'][0]
            visual['checksums'] = {name: hashlib.sha256((project/name).read_bytes()).hexdigest()
                                   for name in ('spec.json','tex.bgra')}
            source.write_bytes(effects.encoded(doc))
            with patch.object(effects, 'MAX_BYTES', 16384):
                info = effects.pack(source, root/'compressed.ffr-effects', root=root)
                self.assertLess(info['unpackedBytes'], 16384)
                self.assertEqual(info['textureCompression']['decodedBytes'], 65536)
                effects.verify(root/'compressed.ffr-effects')
                with self.assertRaisesRegex(ValueError, 'unpacking budget'):
                    effects.pack(source, root/'raw.ffr-effects', root=root, compress_textures=False)
            self.assertFalse((root/'raw.ffr-effects').exists())

    def test_decoder_rejects_truncation_trailing_streams_size_lies_and_wrong_raw_hash(self):
        raw = bytes(range(16)); payload = zlib.compress(raw, 9)
        page = {'pixelSize':[2,2], 'textureEncoding':'zlib', 'textureBytes':16,
                'textureSha256':hashlib.sha256(raw).hexdigest()}
        self.assertEqual(effects.decode_texture(page,payload),raw)
        for broken in (payload[:-1], payload+b'junk', payload+zlib.compress(b''),
                       zlib.compress(raw+b'x'), zlib.compress(raw[:-1]), b'invalid'):
            with self.subTest(payload=broken), self.assertRaises(ValueError):
                effects.decode_texture(page,broken)
        for changes in ({'textureBytes':15}, {'textureBytes':True}, {'textureSha256':'0'*64},
                        {'textureEncoding':'gzip'}, {'pixelSize':[float('inf'),2]}, {'pixelSize':[True,2]},
                        {'pixelSize':[10**400,2]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                effects.decode_texture({**page,**changes},payload)
        with patch.object(effects, 'MAX_TEXTURE_BYTES', 8), patch.object(effects.zlib, 'decompressobj') as decoder:
            with self.assertRaisesRegex(ValueError, 'page budget'):
                effects.decode_texture(page,payload)
            decoder.assert_not_called()
        self.assertEqual(effects.decode_texture({'pixelSize':[2,2]},raw),raw)

    def test_decoded_hash_is_checked_even_if_archive_checksums_are_rebuilt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=fixture(root);output=root/'pack.ffr-effects'
            effects.pack(source,output,root=root)
            files=effects.read_archive(output)
            envelope=json.loads(files['presentation/effects/123.json'])
            presentation=json.loads(files['presentation/123.json'])
            visual=presentation['moves']['GL/ability/7']['visuals'][0]
            name=visual['spec'].removeprefix('data/ffbe/')+'/tex.bgra.z'
            files[name]=zlib.compress(b'\1'*16)
            visual['checksums']['tex.bgra.z']=hashlib.sha256(files[name]).hexdigest()
            files['presentation/123.json']=effects.encoded(presentation)
            for path in (name,'presentation/123.json'):
                envelope['files'][path]={'size':len(files[path]),'sha256':hashlib.sha256(files[path]).hexdigest()}
            files['presentation/effects/123.json']=effects.encoded(envelope)
            with self.assertRaisesRegex(ValueError, 'decoded checksum'):
                effects.verify_files(files,'123',standalone=True)


class ReleaseBoundary(unittest.TestCase):
    def test_release_has_native_audio_adapters_and_no_source_converter(self):
        excluded = build_release.effect_pyinstaller_exclusions()[1::2]
        self.assertIn('convert_ffbe_effects', excluded)
        self.assertIn('ffbe_effects.ibmb', excluded)
        self.assertIn('layer_spec', excluded)
        self.assertIn('prepared_reuse', excluded)
        self.assertIn('ffbe_effects.atomic_files', excluded)
        self.assertNotIn('ffbe_effects.acb_native', excluded)
        with tempfile.TemporaryDirectory() as temp:
            shipped = Path(temp) / 'tools'
            build_release.ship_effect_runtime(shipped)
            for name in ('ffrenv.py', 'ffbe_audio_assets.py', 'ffbe_audio.py', 'ffbe_presentation.py', 'ffbe_effect_bundle.py'):
                shutil.copy2(TOOLS / name, shipped / name)
            build_release.assert_effect_boundary(shipped)
            # An isolated interpreter cannot accidentally import source modules
            # from this checkout and hide a missing packaged dependency.
            code = 'import sys; sys.path.insert(0,sys.argv[1]); import ffbe_audio,ffbe_presentation,ffbe_effect_bundle; import importlib.util; assert importlib.util.find_spec("ffbe_effects.catalog") is None'
            subprocess.run([sys.executable, '-I', '-B', '-c', code, str(shipped)], check=True)
            (shipped / 'ffbe_effects/catalog.py').write_text('# forbidden source lookup')
            with self.assertRaisesRegex(ValueError, 'source conversion'):
                build_release.assert_effect_boundary(shipped)


if __name__ == '__main__':
    unittest.main()
