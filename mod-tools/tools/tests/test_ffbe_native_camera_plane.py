"""Cook actual native camera-plane bytecode, including local storage and guards."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffbe_resonance as resonance
import make_vision_mod as generator
import test_ffbe_native_aura as aura


class NativeCameraPlane(unittest.TestCase):
    command = classmethod(aura.NativeAuraCooked.command.__func__)
    dump = classmethod(aura.NativeAuraCooked.dump.__func__)
    patch = classmethod(aura.NativeAuraCooked.patch.__func__)
    kind = staticmethod(aura.NativeAuraCooked.kind)

    @classmethod
    def setUpClass(cls):
        source = Path(generator.LEGACY) / (resonance.SHELL + '.uasset')
        if not source.is_file(): raise unittest.SkipTest('Native shell unavailable')
        cls.temp = tempfile.TemporaryDirectory(prefix='native-screen-plane-', dir=ROOT / 'build')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name); cls.asset = cls.work / 'shell.uasset'
        cls.usmap = cls.work / 'Mappings.usmap'; shutil.copy2(generator.USMAP, cls.usmap)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix), cls.asset.with_suffix(suffix))
        cls.ids = [k.split(':')[0] for k, v in cls.dump('seqdump').items()
                   if isinstance(v, dict) and v.get('$struct') == 'BTL_SEQUENCE_PARAMETER'][:2]
        cls.settings = [{'EventType': 'NativeScreenPlane', 'NativeScreenPlane_Id': 'screen_' + str(i),
                         'NativeScreenPlane_SourceWidth': 320., 'NativeScreenPlane_SourceHeight': 320.,
                         'NativeScreenPlane_RuntimeScale': .8, 'NativeScreenPlane_OverscanX': 1.06,
                         'NativeScreenPlane_OverscanY': 1.06, 'NativeScreenPlane_FrontDepth': 1000.,
                         'NativeScreenPlane_RearMargin': 300., 'NativeScreenPlane_IsRear': bool(i)} for i in range(2)]
        response = cls.patch([{'asset': 'shell', 'export': i, 'set': s} for i, s in zip(cls.ids, cls.settings)])
        if response.returncode: raise AssertionError(response.stdout + response.stderr)

    def test_native_projection_and_owner_preserving_storage_roundtrip(self):
        settings = self.dump('seqdump'); data = self.dump('tojson')
        imports = data['Imports']
        def walk(value):
            if isinstance(value, dict):
                yield value
                for child in value.values(): yield from walk(child)
            elif isinstance(value, list):
                for child in value: yield from walk(child)
        for identifier, expected in zip(self.ids, self.settings):
            self.assertEqual(next(v for k, v in settings.items() if k.startswith(identifier + ':')), expected)
            fn = data['Exports'][int(identifier) - 1]
            props = {p['Name']: p for p in fn['LoadedProperties']}
            self.assertEqual(props['FFBE_Screen_Sweep']['ElementSize'], 256)
            self.assertEqual(props['FFBE_Screen_Viewport']['ElementSize'], 16)
            self.assertEqual(props['FFBE_Screen_Origin']['ElementSize'], 24)
            self.assertEqual(props['FFBE_Screen_Actors']['ElementSize'], 16)
            calls = [imports[-v['StackNode']-1]['ObjectName'] for v in walk(fn['ScriptBytecode']) if 'StackNode' in v]
            for name in ('GetPlayerCameraManager', 'GetViewportSize', 'GetFOVAngle', 'DegTan',
                         'K2_AttachToComponent', 'SetRelativeScale3D'):
                self.assertIn(name, calls)
            self.assertEqual('GetComponentBounds' in calls, expected['NativeScreenPlane_IsRear'])
            self.assertNotIn('GetBattleUnitByUnitIdWithVision', calls)
            self.assertNotIn('SetActorLocation', calls)
            for item in walk(fn['ScriptBytecode']):
                if isinstance(item.get('New'), dict) and (item['New'].get('Path') or [''])[0].startswith('FFBE_Screen_'):
                    self.assertEqual(item['New']['ResolvedOwner'], int(identifier))

    def test_bad_projection_fails_cleanly_before_package_mutation(self):
        before = self.asset.read_bytes()
        for field, bad in [('NativeScreenPlane_Id', ''), ('NativeScreenPlane_IsRear', 1),
                           ('NativeScreenPlane_RuntimeScale', 0), ('NativeScreenPlane_SourceWidth', 0),
                           ('NativeScreenPlane_OverscanX', .9), ('NativeScreenPlane_FrontDepth', -1)]:
            settings = deepcopy(self.settings[0]); settings[field] = bad
            response = self.patch([{'asset': 'shell', 'export': self.ids[0], 'set': settings}])
            with self.subTest(field=field):
                self.assertEqual(response.returncode, 1)
                self.assertIn('NativeScreenPlane', response.stderr)
                self.assertNotIn('Unhandled exception', response.stderr)
                self.assertEqual(self.asset.read_bytes(), before)


if __name__ == '__main__': unittest.main()
