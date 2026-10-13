"""Cooked resonance isolation must preserve selected actors and prior state."""
from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(Path(__file__).resolve().parent)]
from tools.tests import test_ffbe_native_actor_root as root_test
from tools.tests import test_ffbe_native_aura as aura
import ffbe_resonance as resonance
import make_vision_mod as generator


class NativeResonanceVisibility(unittest.TestCase):
    command = classmethod(aura.NativeAuraCooked.command.__func__)
    dump = classmethod(aura.NativeAuraCooked.dump.__func__)
    patch = classmethod(aura.NativeAuraCooked.patch.__func__)
    kind = staticmethod(aura.NativeAuraCooked.kind)
    walk = staticmethod(root_test.NativeActorRoot.walk)
    vm_size = classmethod(root_test.NativeActorRoot.vm_size.__func__)

    @classmethod
    def setUpClass(cls):
        source = Path(generator.LEGACY) / (resonance.SHELL + '.uasset')
        if not source.is_file():
            raise unittest.SkipTest('Native shell unavailable')
        cls.temp = tempfile.TemporaryDirectory(prefix='native-resonance-visibility-', dir=ROOT / 'build')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name)
        cls.asset = cls.work / 'shell.uasset'
        cls.usmap = cls.work / 'Mappings.usmap'
        shutil.copy2(generator.USMAP, cls.usmap)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if source.with_suffix(suffix).exists():
                shutil.copy2(source.with_suffix(suffix), cls.asset.with_suffix(suffix))
        cls.identifier = next(k.split(':')[0] for k, v in cls.dump('seqdump').items()
                              if isinstance(v, dict) and v.get('$struct') == 'BTL_SEQUENCE_PARAMETER')
        cls.event = {'EventType': 'NativeResonanceVisibility',
                     'NativeResonanceVisibility_UnitId': 13503,
                     'NativeResonanceVisibility_Restore': False}
        cls.op = {'asset': 'shell', 'export': cls.identifier, 'set': cls.event}

    def cooked(self, restore=False, unit=13503):
        op = deepcopy(self.op)
        op['set'].update(NativeResonanceVisibility_Restore=restore, NativeResonanceVisibility_UnitId=unit)
        result = self.patch([op])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        doc = self.dump('tojson')
        fn = doc['Exports'][int(self.identifier) - 1]
        code = fn['ScriptBytecode']
        calls = [e for e in self.walk(code) if 'StackNode' in e]
        named = lambda e: doc['Imports'][-e['StackNode'] - 1]['ObjectName']
        self.assertEqual(next(v for k, v in self.dump('seqdump').items()
                              if k.startswith(self.identifier + ':')), op['set'])
        self.assertEqual(sum(map(self.vm_size, code)), fn['ScriptBytecodeSize'])
        positions = {0}
        for e in code:
            positions.add(max(positions) + self.vm_size(e))
        for e in self.walk(code):
            if self.kind(e) == 'EX_Context_FailSilent':
                self.assertEqual(e['Offset'], self.vm_size(e['ContextExpression']))
            if self.kind(e) in ('EX_Jump', 'EX_JumpIfNot'):
                self.assertIn(e['CodeOffset'], positions)
        return doc, code, calls, named

    def test_hide_keeps_actual_vision_and_entire_target_list(self):
        doc, code, calls, named = self.cooked(unit=13502)
        self.assertEqual(code[0]['Expression']['Value'], 13502)
        getters = [e for e in calls if named(e) == 'GetBattleUnitByUnitIdWithVision']
        self.assertTrue(getters)
        self.assertTrue(all(self.kind(e['Parameters'][1]) == 'EX_False' for e in getters))
        selection = next(e for e in calls if named(e) == 'Array_Contains')
        self.assertEqual(selection['Parameters'][0]['ContextExpression']['Variable']['New']['Path'], ['m_TargetUnitList'])
        self.assertEqual(self.kind(selection['Parameters'][1]), 'EX_ArrayGetByRef')
        self.assertFalse(any('m_pActionUnit' in str(e) for e in code))
        hidden_fields = [e['Variable']['New']['Path'] for e in self.walk(code)
                         if self.kind(e) == 'EX_InstanceVariable']
        self.assertIn(['bHidden'], hidden_fields)
        self.assertIn(['bHiddenInGame'], hidden_fields)
        self.assertNotIn(['bVisible'], hidden_fields)
        setter = next(e for e in calls if named(e) == 'SetActorHiddenInGame')
        self.assertEqual(self.kind(setter['Parameters'][0]), 'EX_True')

    def test_aura_scan_matches_exact_asset_and_preserves_authored_visibility(self):
        doc, code, calls, named = self.cooked()
        equality = next(e for e in calls if named(e) == 'EqualEqual_ObjectObject')
        self.assertEqual(named(equality['Parameters'][0]['ContextExpression']), 'GetAsset')
        asset_import = doc['Imports'][-equality['Parameters'][1]['Value'] - 1]
        self.assertEqual(asset_import['ObjectName'], 'NS_EF_BTL_VisionAura_AuraOnly')
        self.assertEqual(asset_import['ClassName'], 'NiagaraSystem')
        self.assertEqual(doc['Imports'][-asset_import['OuterIndex'] - 1]['ObjectName'],
                         '/Game/Effect/04_BTL/VisionAura/NS_EF_BTL_VisionAura_AuraOnly')
        components = [e for e in self.walk(code) if self.kind(e) == 'EX_StructMemberContext']
        self.assertTrue(components)
        for e in components:
            self.assertEqual(e['StructMemberExpression']['New']['Path'], ['NiagaraComponent'])
            self.assertEqual(e['StructExpression']['ArrayIndex']['Variable']['New']['Path'], ['FFBE_ResonanceVisibility_Index'])
        setter = next(e for e in calls if named(e) == 'SetHiddenInGame')
        self.assertEqual([self.kind(p) for p in setter['Parameters']], ['EX_True', 'EX_False'])
        self.assertFalse(any(named(e) in ('SetVisibility', 'Deactivate', 'DestroyComponent') for e in calls))
        names = {e['Value'] for e in self.walk(code) if self.kind(e) == 'EX_NameConst'}
        self.assertTrue({'FFBE_ResonanceHidden_13503', 'FFBE_ResonanceAura_13503',
                         'FFBE_ResonanceAuraOwner_13503'} <= names)

    def test_restore_uses_changed_owners_without_current_vision_or_registry(self):
        doc, code, calls, named = self.cooked(restore=True)
        self.assertFalse(any(named(e) in ('GetBattleUnitByUnitIdWithVision', 'GetAsset', 'Array_Contains', 'Array_AddUnique') for e in calls))
        self.assertNotIn('m_SsNiagaraDatas', str(code))
        self.assertNotIn('m_TargetUnitList', str(code))
        enumerations = [e for e in calls if named(e) == 'GetAllActorsWithTag']
        self.assertEqual([e['Parameters'][1]['Value'] for e in enumerations],
                         ['FFBE_ResonanceHidden_13503', 'FFBE_ResonanceAuraOwner_13503'])
        query = next(e for e in calls if named(e) == 'GetComponentsByTag')
        self.assertEqual(query['Parameters'][1]['Value'], 'FFBE_ResonanceAura_13503')
        self.assertEqual(doc['Imports'][-query['Parameters'][0]['Value'] - 1]['ObjectName'], 'NiagaraComponent')
        setter = next(e for e in calls if named(e) == 'SetHiddenInGame')
        self.assertEqual([self.kind(p) for p in setter['Parameters']], ['EX_False', 'EX_False'])
        self.assertEqual(sum(named(e) == 'Array_RemoveItem' for e in calls), 3)
        self.assertTrue(all(self.kind(e['Parameters'][0]) == 'EX_False'
                            for e in calls if named(e) == 'SetActorHiddenInGame'))

    def test_invalid_contract_is_rejected_without_file_changes(self):
        self.cooked()
        before = self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()
        for key, value in [('NativeResonanceVisibility_UnitId', 0), ('NativeResonanceVisibility_UnitId', True),
                           ('NativeResonanceVisibility_UnitId', 2**31), ('NativeResonanceVisibility_Restore', 1),
                           ('extra', True)]:
            op = deepcopy(self.op)
            op['set'][key] = value
            result = self.patch([op])
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, (self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()))

    def test_corrupt_target_selection_is_rejected_on_readback(self):
        self.cooked()
        bad = self.work / 'bad-selection.uasset'
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if self.asset.with_suffix(suffix).exists():
                shutil.copy2(self.asset.with_suffix(suffix), bad.with_suffix(suffix))
        raw = bad.read_bytes()
        self.assertEqual(raw.count(b'Array_Contains\x00'), 1)
        bad.write_bytes(raw.replace(b'Array_Contains\x00', b'Array_Containx\x00', 1))
        result = self.command('seqdump', bad, self.work / 'bad-selection.json')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Malformed NativeResonanceVisibility', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
