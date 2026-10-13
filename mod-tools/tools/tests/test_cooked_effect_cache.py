import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cooked_effect_cache as cache


class CookedCacheTests(unittest.TestCase):
    def test_corrupt_cache_is_rejected_and_repaired_before_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root / 'source'; source.mkdir()
            (source / 'effect.uasset').write_bytes(b'header')
            (source / 'effect.uexp').write_bytes(b'verified pixels')
            cache.store(root / 'cache', 'key', source)
            self.assertTrue(cache.restore(root / 'cache', 'key', root / 'out'))
            (root / 'cache/key/effect.uexp').write_bytes(b'corrupt')
            self.assertFalse(cache.restore(root / 'cache', 'key', root / 'bad'))
            self.assertFalse((root / 'bad').exists())
            cache.store(root / 'cache', 'key', source)
            self.assertTrue(cache.restore(root / 'cache', 'key', root / 'repaired'))
            self.assertEqual((root / 'repaired/effect.uexp').read_bytes(), b'verified pixels')

    def test_geometry_pixels_and_compiler_changes_invalidate_cooked_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); media = root / 'media'; media.mkdir()
            (media / 'spec.json').write_text(json.dumps({'textureFile':'tex.bgra'}))
            (media / 'tex.bgra').write_bytes(b'pixels')
            mapping = root / 'Mappings.usmap'; mapping.write_bytes(b'mapping')
            compiler = root / 'compiler.dll'; compiler.write_bytes(b'compiler')
            def identity(): return cache.identity(root, root / 'legacy', mapping, compiler, 'effect', 'media', 1, 2)
            original = identity()
            (media / 'tex.bgra').write_bytes(b'changed pixels')
            changed = identity(); self.assertNotEqual(original, changed)
            compiler.write_bytes(b'new compiler')
            self.assertNotEqual(changed, identity())


if __name__ == '__main__': unittest.main()
