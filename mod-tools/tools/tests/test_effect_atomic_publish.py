import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/ffbe_effects')]
from ffbe_effects import atomic_files, to_ss6


class EffectAtomicPublish(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_json_contents_match_the_previous_compact_serialization(self):
        value={'name':'ソラ','moves':[1,2]}
        path=self.root/'manifest.json'
        atomic_files.write_json(path,value,ensure_ascii=False,separators=(',',':'))
        self.assertEqual(path.read_bytes(),json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())
        self.assertEqual(list(self.root.iterdir()),[path])

    def test_failed_replacement_keeps_previous_document_and_removes_temporary_file(self):
        path=self.root/'manifest.json';path.write_bytes(b'previous complete document')
        with patch.object(atomic_files.os,'replace',side_effect=PermissionError('reader lock')):
            with self.assertRaises(PermissionError):atomic_files.write_json(path,{'next':1})
        self.assertEqual(path.read_bytes(),b'previous complete document')
        self.assertEqual(list(self.root.iterdir()),[path])

    def test_old_cache_with_missing_or_truncated_atlas_is_not_complete(self):
        (self.root/'spec.json').write_text(json.dumps({'cellmaps':[
            {'pixelSize':[2,2],'textureFile':'tex.bgra'},
            {'pixelSize':[2,1],'textureFile':'tex_1.bgra'}]}))
        (self.root/'tex.bgra').write_bytes(bytes(16))
        self.assertFalse(to_ss6.complete_export(self.root))
        (self.root/'tex_1.bgra').write_bytes(bytes(7))
        self.assertFalse(to_ss6.complete_export(self.root))
        (self.root/'tex_1.bgra').write_bytes(bytes(8))
        self.assertTrue(to_ss6.complete_export(self.root))

    def test_windows_sharing_denial_retries_without_exposing_partial_json(self):
        path=self.root/'report.json';path.write_text('{"old":1}')
        replace=atomic_files.os.replace
        attempts=[]
        def locked_then_available(source,target):
            attempts.append(1)
            self.assertEqual(json.loads(path.read_bytes()),{'old':1})
            if len(attempts)<3:
                error=PermissionError('sharing violation');error.winerror=5
                raise error
            replace(source,target)
        with patch.object(atomic_files.os,'replace',side_effect=locked_then_available),patch.object(atomic_files.time,'sleep'):
            atomic_files.write_json(path,{'new':2})
        self.assertEqual(json.loads(path.read_bytes()),{'new':2})
        self.assertEqual(len(attempts),3)
        self.assertEqual(list(self.root.iterdir()),[path])

    def test_windows_retry_is_bounded_and_preserves_previous_report(self):
        path=self.root/'report.json';path.write_bytes(b'previous')
        error=PermissionError('sharing violation');error.winerror=32
        with patch.object(atomic_files.os,'replace',side_effect=error) as replace,patch.object(atomic_files.time,'sleep'):
            with self.assertRaises(PermissionError):atomic_files.write_json(path,{'new':2})
        self.assertEqual(replace.call_count,20)
        self.assertEqual(path.read_bytes(),b'previous')
        self.assertEqual(list(self.root.iterdir()),[path])

    def test_interrupted_atlas_export_does_not_publish_a_completion_spec(self):
        from PIL import Image
        doc={'textures':['fixture'],'frames':[[{'tex':0,'uv':[0,0,2,2],'scale':[1,1],
            'pos':[0,0],'rot':0,'alpha':1,'color':[1,1,1],'blend':'mix'}]],'fps':60,'pixelsPerUnit':2.4}
        with (patch.object(to_ss6,'load_texture',return_value=Image.new('RGBA',(2,2),'white')),
              patch.object(Image.Image,'save',side_effect=OSError('interrupted disk write'))):
            with self.assertRaises(OSError):to_ss6.convert(doc,str(self.root),'test')
        self.assertFalse((self.root/'spec.json').exists())

    def test_empty_source_fails_descriptively_without_publishing_an_asset(self):
        with self.assertRaisesRegex(ValueError,'no drawable sprite frames'):
            to_ss6.convert({'textures':[],'frames':[[]]},str(self.root),'empty')
        self.assertFalse((self.root/'spec.json').exists())

    def test_empty_source_is_a_gap_even_when_another_group_member_draws(self):
        from ffbe_effects.rendered_coverage import record_empty_sources
        spawns=[{'file':'empty.bmb','frame':0},{'file':'art.bmb','frame':1}]
        docs={'empty.bmb':{'frames':[[]],'textures':[]},'art.bmb':{'frames':[[{'tex':0}]]}}
        entry={'visualCoverage':{'complete':True,'omitted':[]},'issues':[]}
        record_empty_sources(entry,spawns,docs,{'empty.bmb':{'declaredFrames':90}})
        self.assertFalse(entry['visualCoverage']['complete'])
        self.assertEqual(entry['visualCoverage']['omitted'][0]['spawn'],spawns[0])
        self.assertEqual(entry['visualCoverage']['omitted'][0]['decoderEvidence']['declaredFrames'],90)
        self.assertEqual(len(entry['issues']),1)


if __name__=='__main__':unittest.main()
