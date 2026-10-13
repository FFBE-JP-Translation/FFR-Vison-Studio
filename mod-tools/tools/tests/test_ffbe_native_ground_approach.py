"""Ground approach compiles to guarded native socket-height compensation."""
from copy import deepcopy
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from tools.tests import test_ffbe_native_aura as aura
from tools.tests import test_ffbe_native_stage_camera as stage
import ffbe_resonance as resonance
import make_vision_mod as generator


class NativeGroundApproach(unittest.TestCase):
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
        cls.temp = tempfile.TemporaryDirectory(prefix='native-ground-approach-', dir=ROOT/'build')
        cls.addClassCleanup(cls.temp.cleanup); cls.work = Path(cls.temp.name); cls.asset = cls.work/'shell.uasset'
        cls.usmap = cls.work/'Mappings.usmap'; shutil.copy2(generator.USMAP, cls.usmap)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix), cls.asset.with_suffix(suffix))
        cls.identifier = next(k.split(':')[0] for k,v in cls.dump('seqdump').items()
                              if isinstance(v, dict) and v.get('$struct') == 'BTL_SEQUENCE_PARAMETER')
        cls.event = {'EventType': 'NativeGroundApproach', 'NativeGroundApproach_UnitId': 7777,
            'NativeGroundApproach_Frame': 12, 'NativeGroundApproach_PartName': 'Null_root',
            'NativeGroundApproach_Offset': {'x': 12., 'y': 34., 'z': 0.}}
        cls.op = {'asset': 'shell', 'export': cls.identifier, 'set': cls.event}
        response = cls.patch([cls.op])
        if response.returncode: raise AssertionError(response.stdout + response.stderr)

    def test_native_fields_and_height_mask_preserve_original_ground(self):
        data = self.dump('tojson'); fn = data['Exports'][int(self.identifier)-1]; code = fn['ScriptBytecode']
        imports = data['Imports']
        def named(call): return imports[-call['StackNode']-1]['ObjectName']
        self.assertEqual([self.kind(e) for e in code], ['EX_JumpIfNot']*6 + ['EX_LocalVirtualFunction', 'EX_Return', 'EX_EndOfScript'])
        self.assertEqual(fn['ScriptBytecodeSize'], sum(map(self.vm_size, code)))
        end = sum(map(self.vm_size, code[:7]))
        self.assertEqual([e['CodeOffset'] for e in code[:6]], [end]*6)
        expressions = list(self.walk(code))
        constants = code[6]['Parameters'][1]['Value']
        part_index = next(i for i,e in enumerate(constants) if self.kind(e) == 'EX_NameConst' and e['Value'] == 'Null_root')
        self.assertEqual(constants[part_index-1]['Value'], 12)
        self.assertEqual(float(constants[part_index+2]['Value']), 0.)  # no added trajectory arc
        self.assertEqual(float(constants[part_index+4]['Value']), 1.5)
        self.assertEqual(constants[part_index+5]['Value'], 2)
        self.assertEqual(self.kind(constants[part_index+6]), 'EX_True')  # no extra clearance displacement
        self.assertEqual(self.kind(constants[part_index+7]), 'EX_True')  # selected vision moves
        calls = [e for e in expressions if 'StackNode' in e]
        adds = [e for e in calls if named(e) == 'Add_VectorVector']; self.assertEqual(len(adds), 1)
        add = adds[0]
        self.assertEqual([float(add['Parameters'][0]['Value'][k]) for k in 'XYZ'], [12., 34., 0.])
        multiply = add['Parameters'][1]; self.assertEqual(named(multiply), 'Multiply_VectorVector')
        self.assertEqual([float(multiply['Parameters'][1]['Value'][k]) for k in 'XYZ'], [0., 0., 1.])
        difference = multiply['Parameters'][0]; self.assertEqual(named(difference), 'Subtract_VectorVector')
        caster, target_socket = difference['Parameters']
        self.assertEqual(named(caster['ContextExpression']), 'K2_GetActorLocation')
        self.assertEqual(named(caster['ObjectExpression']), 'GetBattleUnitByUnitIdWithVision')
        self.assertEqual(caster['ObjectExpression']['Parameters'][0]['Value'], 7777)
        self.assertEqual(named(target_socket['ContextExpression']), 'GetSocketLocation')
        self.assertEqual(target_socket['ContextExpression']['Parameters'][0]['Value'], 'Null_root')
        self.assertEqual(target_socket['ObjectExpression']['ContextExpression']['Variable']['New']['Path'], ['m_pSsPlayerComponent'])
        self.assertEqual(named(code[5]['BooleanExpression']['ContextExpression']), 'DoesSocketExist')
        for expression in expressions:
            if self.kind(expression) == 'EX_Context_FailSilent':
                self.assertEqual(expression['Offset'], self.vm_size(expression['ContextExpression']))
        self.assertEqual(next(v for k,v in self.dump('seqdump').items() if k.startswith(self.identifier+':')), self.event)
        # Independent endpoint oracle includes high target sockets and shifted
        # battlefield ground. Vertical endpoint is always the caster's old Z.
        for caster, socket in (([0, 200, 0], [10, -300, 500]), ([22, 18, 76], [-3, 14, -90])):
            offset = [12, 34, caster[2]-socket[2]]
            self.assertEqual([a+b for a,b in zip(socket, offset)], [socket[0]+12, socket[1]+34, caster[2]])

    def test_vertical_offset_and_bad_parameters_fail_without_mutation(self):
        before = self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()
        for field, value in [('NativeGroundApproach_UnitId', 0), ('NativeGroundApproach_Frame', 0),
            ('NativeGroundApproach_Frame', True), ('NativeGroundApproach_PartName', ''),
            ('NativeGroundApproach_Offset', {'x': 0, 'y': 0, 'z': 56})]:
            bad = deepcopy(self.op); bad['set'][field] = value
            response = self.patch([bad]); self.assertNotEqual(response.returncode, 0)
            self.assertIn('NativeGroundApproach', response.stdout+response.stderr)
        self.assertEqual(before, (self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()))

    def test_corrupt_ground_mask_rejected_on_readback(self):
        asset = self.work/'bad-mask.uasset'
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            source = self.asset.with_suffix(suffix)
            if source.exists(): shutil.copy2(source, asset.with_suffix(suffix))
        payload = asset.with_suffix('.uexp'); raw = payload.read_bytes()
        marker = b'\x23'+struct.pack('<ddd', 0, 0, 1)
        self.assertIn(marker, raw)
        payload.write_bytes(raw.replace(marker, b'\x23'+struct.pack('<ddd', 0, 1, 1), 1))
        response = self.command('seqdump', asset, self.work/'bad-mask-dump.json')
        self.assertNotEqual(response.returncode, 0)
        self.assertIn('Malformed NativeGroundApproach', response.stdout+response.stderr)


if __name__ == '__main__': unittest.main()
