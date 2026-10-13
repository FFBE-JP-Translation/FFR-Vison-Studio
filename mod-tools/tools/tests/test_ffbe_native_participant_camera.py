"""Cook/read native participant midpoint math and reject malformed VM bodies."""
from copy import deepcopy
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.tests import test_ffbe_native_aura as aura
from tools.tests import test_ffbe_native_stage_camera as stage
import ffbe_resonance as resonance
import make_vision_mod as generator


class NativeParticipantCamera(unittest.TestCase):
    command = classmethod(aura.NativeAuraCooked.command.__func__)
    dump = classmethod(aura.NativeAuraCooked.dump.__func__)
    patch = classmethod(aura.NativeAuraCooked.patch.__func__)
    kind = staticmethod(aura.NativeAuraCooked.kind)
    vm_size = classmethod(stage.NativeStageCameraCooked.vm_size.__func__)
    walk = staticmethod(stage.NativeStageCameraCooked.walk)

    @classmethod
    def setUpClass(cls):
        source = Path(generator.LEGACY)/(resonance.SHELL+'.uasset')
        if not source.is_file(): raise unittest.SkipTest('Native battle shell unavailable')
        cls.temp = tempfile.TemporaryDirectory(prefix='native-participant-camera-', dir=ROOT/'build')
        cls.addClassCleanup(cls.temp.cleanup); cls.work = Path(cls.temp.name); cls.asset = cls.work/'shell.uasset'
        cls.usmap = cls.work/'Mappings.usmap'; shutil.copy2(generator.USMAP, cls.usmap)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix), cls.asset.with_suffix(suffix))
        cls.identifier = next(k.split(':')[0] for k,v in cls.dump('seqdump').items()
                              if isinstance(v, dict) and v.get('$struct') == 'BTL_SEQUENCE_PARAMETER')
        cls.event = {'EventType': 'NativeParticipantCamera', 'NativeParticipantCamera_UnitId': 7777,
                     'NativeParticipantCamera_Frame': 12}
        cls.op = {'asset': 'shell', 'export': cls.identifier, 'set': cls.event}
        response = cls.patch([cls.op])
        if response.returncode: raise AssertionError(response.stdout + response.stderr)

    def test_cooked_midpoint_uses_both_actual_actor_positions_and_native_target_base(self):
        data = self.dump('tojson'); fn = data['Exports'][int(self.identifier)-1]; code = fn['ScriptBytecode']
        imports = data['Imports']
        def named(call): return imports[-call['StackNode']-1]['ObjectName']
        self.assertEqual([self.kind(e) for e in code], ['EX_JumpIfNot']*5 + ['EX_LocalVirtualFunction', 'EX_Return', 'EX_EndOfScript'])
        self.assertEqual(fn['ScriptBytecodeSize'], sum(map(self.vm_size, code)))
        end = sum(map(self.vm_size, code[:6]))
        self.assertEqual([e['CodeOffset'] for e in code[:5]], [end]*5)
        sc = code[5]['Parameters'][1]
        self.assertEqual(sc['Value'][0]['Value'], 4)  # native CameraSetLookAtTarget
        self.assertEqual(sc['Value'][15]['Value'], 12)
        self.assertEqual(sc['Value'][19]['Value'], -1)  # actual selected actor-root mode
        multiply = sc['Value'][14]
        self.assertEqual(named(multiply), 'Multiply_VectorFloat')
        self.assertEqual(self.kind(multiply['Parameters'][1]), 'EX_DoubleConst')
        self.assertEqual(float(multiply['Parameters'][1]['Value']), .5)
        difference = multiply['Parameters'][0]
        self.assertEqual(named(difference), 'Subtract_VectorVector')
        vision, target = difference['Parameters']
        for location in (vision, target): self.assertEqual(named(location['ContextExpression']), 'K2_GetActorLocation')
        self.assertEqual(named(vision['ObjectExpression']), 'GetBattleUnitByUnitIdWithVision')
        self.assertEqual(vision['ObjectExpression']['Parameters'][0]['Value'], 7777)
        self.assertEqual(target['ObjectExpression']['ArrayVariable']['ContextExpression']['Variable']['New']['Path'], ['m_TargetUnitList'])
        for expression in self.walk(code):
            if self.kind(expression) == 'EX_Context_FailSilent':
                self.assertEqual(expression['Offset'], self.vm_size(expression['ContextExpression']))
        self.assertEqual(next(v for k,v in self.dump('seqdump').items() if k.startswith(self.identifier+':')), self.event)
        # Independent point oracle demonstrates translation equivariance and
        # target-dependent movement. There is no form-specific magic offset.
        for caster, enemy in (([100, 500, 0], [-20, -600, 130]), ([31, 7, 20], [31, 7, 20])):
            offset = [(a-b)*.5 for a,b in zip(caster, enemy)]
            self.assertEqual([b+d for b,d in zip(enemy, offset)], [(a+b)*.5 for a,b in zip(caster, enemy)])

    def test_malformed_interface_fails_before_mutating_package(self):
        before = self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()
        for field, value in [('NativeParticipantCamera_UnitId', 0), ('NativeParticipantCamera_UnitId', True),
                             ('NativeParticipantCamera_Frame', 0), ('NativeParticipantCamera_Frame', 121),
                             ('NativeParticipantCamera_Frame', 12.0), ('NativeParticipantCamera_Frame', '12')]:
            bad = deepcopy(self.op); bad['set'][field] = value
            with self.subTest(field=field, value=value):
                result = self.patch([bad]); self.assertNotEqual(result.returncode, 0)
                self.assertIn('NativeParticipantCamera', result.stdout+result.stderr)
        self.assertEqual(before, (self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()))

    def test_corrupt_midpoint_or_guard_rejected_by_independent_readback(self):
        data = self.dump('tojson'); code = data['Exports'][int(self.identifier)-1]['ScriptBytecode']
        for label, marker, replacement in (
            ('guard', struct.pack('<BI', 7, code[0]['CodeOffset']), struct.pack('<BI', 7, code[0]['CodeOffset']-1)),
            ('midpoint', b'\x37'+struct.pack('<d', .5), b'\x37'+struct.pack('<d', .6))):
            asset = self.work/(label+'.uasset')
            for suffix in ('.uasset', '.uexp', '.ubulk'):
                source = self.asset.with_suffix(suffix)
                if source.exists(): shutil.copy2(source, asset.with_suffix(suffix))
            payload = asset.with_suffix('.uexp'); raw = payload.read_bytes()
            self.assertIn(marker, raw)
            payload.write_bytes(raw.replace(marker, replacement, 1))
            result = self.command('seqdump', asset, self.work/(label+'-dump.json'))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Malformed NativeParticipantCamera', result.stdout+result.stderr)


if __name__ == '__main__': unittest.main()
