"""Prepared catalogs must not scan an unrelated raw client on the same PC."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffbe_catalog as catalog


class SpriteRoots(unittest.TestCase):
    def test_prepared_catalog_uses_local_sprites_without_raw_client_scan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = root/'pack'
            pack.mkdir()
            (pack/'catalog.json').write_text('{}')
            sprite = pack/'sprites/100'
            sprite.mkdir(parents=True)
            (sprite/'unit_anime_100.png').write_bytes(catalog.PNG_MAGIC)
            external = root/'raw-client'
            external.mkdir()
            (external/'unit_anime_200.png').write_bytes(catalog.PNG_MAGIC)
            roots = [(str(pack/'sprites'), 'perform', 'pack'),
                     (str(external), 'flat', 'gl_extracted')]
            original_listdir = catalog.os.listdir

            def guarded(path):
                if Path(path) == external:
                    raise AssertionError('Prepared import scanned the raw client')
                return original_listdir(path)

            with patch.object(catalog, 'PACK', str(pack)), patch.object(catalog, 'SPRITE_ROOTS', roots), \
                 patch.object(catalog, '_sprite_map', None), patch.object(catalog, '_locked', None), \
                 patch.object(catalog.os, 'listdir', side_effect=guarded):
                self.assertEqual({'100': (str(sprite), 'pack')}, catalog.sprite_map())

            # Developer workspaces with no prepared catalog retain discovery.
            (pack/'catalog.json').unlink()
            with patch.object(catalog, 'PACK', str(pack)), patch.object(catalog, 'SPRITE_ROOTS', roots), \
                 patch.object(catalog, '_sprite_map', None), patch.object(catalog, '_locked', None):
                self.assertEqual({'100', '200'}, set(catalog.sprite_map()))


if __name__ == '__main__':
    unittest.main()
