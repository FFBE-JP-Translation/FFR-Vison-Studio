"""Asset reuse follows content, never tables or temporary output paths."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cooked_command_cache as cache


class CommandCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('compiler.dll', 'UAssetAPI.dll', 'donor.uasset', 'donor.uexp', 'spec.json', 'Mappings.usmap'):
            (self.root/name).write_bytes(name.encode())
        self.calls = 0
        self.args = ['dotnet', str(self.root/'compiler.dll'), 'make-ss6', str(self.root/'donor.uasset'),
                     str(self.root/'spec.json'), str(self.root/'first/New.uasset'), '/Game/Old', '/Game/New',
                     '--usmap', str(self.root/'Mappings.usmap')]

    def execute(self, args):
        self.calls += 1
        output = Path(args[5]); output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b'header'); output.with_suffix('.uexp').write_bytes(b'pixels')
        return 'constructed'

    def cook(self):
        return cache.run(self.args, self.execute, self.root/'cache')

    def test_reuses_identical_content_across_new_work_directories(self):
        self.cook()
        self.args[5] = str(self.root/'second/New.uasset')
        self.cook()
        self.assertEqual(self.calls, 1)
        self.assertEqual((self.root/'second/New.uexp').read_bytes(), b'pixels')

    def test_changed_payload_donor_mapping_compiler_and_reference_invalidate(self):
        self.cook()
        for name in ('spec.json', 'donor.uexp', 'Mappings.usmap', 'UAssetAPI.dll'):
            with self.subTest(name=name):
                (self.root/name).write_bytes(b'new content '+name.encode())
                before = self.calls; self.cook(); self.assertEqual(self.calls, before+1)
        self.args[7] = '/Game/Other'
        self.cook(); self.assertEqual(self.calls, 6)

    def test_corrupt_artifact_is_rebuilt(self):
        self.cook()
        asset = next((self.root/'cache').glob('*/New.uexp'))
        asset.write_bytes(b'broken')
        self.cook(); self.assertEqual(self.calls, 2)
        self.assertEqual((self.root/'first/New.uexp').read_bytes(), b'pixels')

    def test_texture_dimensions_are_part_of_the_key(self):
        self.args[2] = 'make-texture'
        self.args[5:5] = ['64', '64']
        def execute(args):
            self.calls += 1
            Path(args[7]).write_bytes(b'pixels')
            return ''
        for width in ('64', '64', '128'):
            self.args[5] = width
            cache.run(self.args, execute, self.root/'cache')
        self.assertEqual(self.calls, 2)

    def test_table_commands_are_never_cached(self):
        calls = []
        for _ in range(2):
            cache.run(['dotnet', 'compiler', 'patch', 'table.json'], lambda a: calls.append(a), self.root/'cache')
        self.assertEqual(len(calls), 2)
        self.assertFalse((self.root/'cache').exists())

    def test_self_contained_compiler_is_also_cached(self):
        args = self.args[1:]
        def execute(command):
            return self.execute(['dotnet', *command])
        for _ in range(2): cache.run(args, execute, self.root/'cache')
        self.assertEqual(self.calls, 1)


if __name__ == '__main__': unittest.main()
