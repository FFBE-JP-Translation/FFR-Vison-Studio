"""Portable texture storage must yield the original native upload bytes."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import make_vision_mod as builder


class PreparedTextureCook(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.raw=bytes(range(256))*4
        self.page={'pixelSize':[16,16],'textureFile':'tex.bgra.z','textureEncoding':'zlib',
                   'textureBytes':len(self.raw),'textureSha256':hashlib.sha256(self.raw).hexdigest()}
        self.encoded=zlib.compress(self.raw,9)
        self.source=self.root/'tex.bgra.z'
        self.source.write_bytes(self.encoded)

    def decode(self, page=None):
        return Path(builder.prepared_texture_payload(str(self.source),page or self.page,str(self.root/'cache')))

    def test_lossless_cached_upload_repairs_modified_bytes_and_preserves_preparation(self):
        output=self.decode()
        self.assertEqual(self.raw,output.read_bytes())
        self.assertEqual(output,self.decode())
        output.write_bytes(bytes(len(self.raw)))
        self.assertEqual(output,self.decode())
        self.assertEqual(self.raw,output.read_bytes())
        self.assertEqual(self.encoded,self.source.read_bytes())

    def test_invalid_payload_cannot_replace_a_valid_native_upload(self):
        output=self.decode()
        for payload,page in ((self.encoded[:-3],self.page),
                             (self.encoded+b'trailing',self.page),
                             (self.encoded,{**self.page,'textureSha256':'0'*64}),
                             (zlib.compress(self.raw*2),self.page)):
            with self.subTest(payload=len(payload),page=page):
                self.source.write_bytes(payload)
                with self.assertRaises(ValueError):self.decode(page)
                self.assertEqual(self.raw,output.read_bytes())
        self.assertEqual([output],list((self.root/'cache').iterdir()))

    def test_effect_build_passes_decoded_bytes_to_unchanged_native_texture_cooker(self):
        spec={'cellmapName':'prepared','pixelSize':[16,16],**self.page}
        (self.root/'spec.json').write_text(json.dumps(spec))
        calls=[]
        with patch.object(builder,'ROOT',str(self.root)),patch.object(builder,'BUILD',str(self.root/'work')), \
                patch.object(builder,'OUT',str(self.root/'cooked')),patch.object(builder,'run',side_effect=calls.append):
            builder.build_effect_project('prepared','.',13110)
        texture=next(command for command in calls if 'make-texture' in command)
        argument=texture.index('make-texture')
        self.assertEqual(self.raw,Path(texture[argument+2]).read_bytes())
        self.assertEqual(['16','16'],texture[argument+3:argument+5])
        self.assertEqual(self.encoded,self.source.read_bytes())

    def test_legacy_raw_texture_needs_no_storage_adapter(self):
        self.assertEqual(str(self.source),builder.prepared_texture_payload(str(self.source),{'pixelSize':[16,16]}))
        self.assertFalse((self.root/'cache').exists())


if __name__=='__main__':
    unittest.main()
