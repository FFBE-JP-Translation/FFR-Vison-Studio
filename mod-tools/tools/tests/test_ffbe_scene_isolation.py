"""Cooked actor isolation: participant selection, prior-hidden state and cleanup."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_vision_mod as generator
import ffbe_resonance as resonance
import test_ffbe_native_aura as aura
import test_ffbe_native_stage_camera as camera_tests


class SceneIsolationCooked(unittest.TestCase):
    command = classmethod(aura.NativeAuraCooked.command.__func__)
    dump = classmethod(aura.NativeAuraCooked.dump.__func__)
    patch = classmethod(aura.NativeAuraCooked.patch.__func__)
    kind = staticmethod(aura.NativeAuraCooked.kind)

    @classmethod
    def setUpClass(cls):
        source = Path(generator.LEGACY) / (resonance.SHELL + '.uasset')
        if not source.is_file(): raise unittest.SkipTest('Native battle shell unavailable')
        cls.temp = tempfile.TemporaryDirectory(prefix='scene-isolation-', dir=ROOT / 'build')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name); cls.asset = cls.work / 'shell.uasset'
        cls.usmap = cls.work / 'Mappings.usmap'; shutil.copy2(generator.USMAP, cls.usmap)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix), cls.asset.with_suffix(suffix))
        cls.ids = [k.split(':')[0] for k, v in cls.dump('seqdump').items()
                   if isinstance(v, dict) and v.get('$struct') == 'BTL_SEQUENCE_PARAMETER'][:2]
        cls.events = [{'EventType': 'NativeStageVisibility', 'NativeStageVisibility_UnitId': 13503,
                       'NativeStageVisibility_Restore': restore} for restore in (False, True)]
        result = cls.patch([{'asset': 'shell', 'export': identifier, 'set': event}
                            for identifier, event in zip(cls.ids, cls.events)])
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def vm_size(cls, e):
        if cls.kind(e) == 'EX_Jump': return 5
        return camera_tests.NativeStageCameraCooked.vm_size.__func__(cls, e)

    def test_cooked_visibility_is_scoped_and_roundtrips(self):
        dumped = self.dump('seqdump')
        for identifier, event in zip(self.ids, self.events):
            self.assertEqual(next(v for k, v in dumped.items() if k.split(':')[0] == identifier), event)
        doc = self.dump('tojson')
        for identifier in self.ids:
            fn = doc['Exports'][int(identifier)-1]
            self.assertIn('FUNC_HasDefaults', fn['FunctionFlags'])
            local = next(p for p in fn['LoadedProperties'] if p['Name'] == 'FFBE_StageActors')
            self.assertEqual(local['ElementSize'], 16)
            self.assertEqual(local['ArrayDim'], 'TArray')  # native scalar dimension 1
            self.assertEqual(local['Inner']['ElementSize'], 8)
            self.assertEqual(local['Inner']['ArrayDim'], 'TArray')
            code = fn['ScriptBytecode']; offsets = []; at = 0
            for e in code:
                offsets.append(at); at += self.vm_size(e)
            self.assertEqual(at, fn['ScriptBytecodeSize'])
            for e in code:
                if self.kind(e) in ('EX_Jump', 'EX_JumpIfNot'): self.assertIn(e['CodeOffset'], offsets)
            self.assertEqual(sum(self.kind(e) == 'EX_Jump' for e in code), 1)

    def run_cooked(self, fn, actors, event, selected):
        """Execute the emitted control flow against a small native-call model.

        This evaluates the actual serialized guards/loops, not a restatement
        of the desired visibility algorithm.
        """
        doc = self.document
        imports = doc['Imports']; local = {'FFBE_StageActors': []}
        local[fn['LoadedProperties'][0]['Name']] = event
        def resolve(i): return imports[-i-1]['ObjectName']
        def eval_expr(e, context=None):
            kind = self.kind(e)
            if kind == 'EX_True': return True
            if kind == 'EX_False': return False
            if kind == 'EX_IntZero': return 0
            if kind in ('EX_IntConst', 'EX_NameConst'): return e['Value']
            if kind == 'EX_ObjectConst': return resolve(e['Value'])
            if kind in ('EX_InstanceVariable', 'EX_LocalVariable'):
                path = e['Variable']['New']['Path']; result = local if kind == 'EX_LocalVariable' else context
                for name in path: result = result[name]
                return result
            if kind == 'EX_Context_FailSilent':
                return eval_expr(e['ContextExpression'], eval_expr(e['ObjectExpression']))
            if kind == 'EX_ArrayGetByRef': return eval_expr(e['ArrayVariable'])[eval_expr(e['ArrayIndex'])]
            if kind in ('EX_CallMath', 'EX_FinalFunction'):
                name = resolve(e['StackNode']); args = [eval_expr(p) for p in e['Parameters']]
                if name == 'IsValid': return args[0] is not None
                if name == 'GetBattleUnitByUnitIdWithVision': return selected if args == [13503, False] else None
                if name == 'GetAllActorsOfClass': args[2][:] = actors[:]; return None
                if name == 'Array_IsValidIndex': return 0 <= args[1] < len(args[0])
                if name == 'Array_LastIndex': return len(args[0])-1
                if name == 'NotEqual_ObjectObject': return args[0] is not args[1]
                if name == 'Not_PreBool': return not args[0]
                if name == 'Array_Add': args[0].append(args[1]); return len(args[0])-1
                if name == 'Array_Remove': args[0].pop(args[1]); return None
                if name == 'Array_RemoveItem': args[0].remove(args[1]); return True
                if name == 'ActorHasTag': return args[0] in context['Tags']
                if name == 'SetActorHiddenInGame': context['bHidden'] = args[0]; return None
                raise AssertionError(name)
            raise AssertionError(kind)
        code = fn['ScriptBytecode']; offsets = {}; offset = 0
        for i, e in enumerate(code): offsets[offset] = i; offset += self.vm_size(e)
        at = 0; steps = 0
        while at < len(code):
            e = code[at]; kind = self.kind(e); steps += 1
            self.assertLess(steps, 1000, 'Cooked loop did not terminate')
            if kind in ('EX_Return', 'EX_EndOfScript'): return
            if kind == 'EX_Jump': at = offsets[e['CodeOffset']]; continue
            if kind == 'EX_JumpIfNot':
                if not eval_expr(e['BooleanExpression']): at = offsets[e['CodeOffset']]; continue
            else: eval_expr(e)
            at += 1

    def test_actual_cooked_loop_preserves_participants_and_prior_hidden_actors(self):
        self.document = self.dump('tojson')
        actor = lambda hidden=False: {'bHidden': hidden, 'Tags': []}
        party, other_enemy, vision, target, previously_hidden = actor(), actor(), actor(), actor(), actor(True)
        actors = [party, None, other_enemy, vision, target, previously_hidden]
        event = {'m_pActionUnit': party, 'm_TargetUnitList': [target]}
        hide, restore = [self.document['Exports'][int(i)-1] for i in self.ids]
        self.run_cooked(hide, actors, event, vision)
        self.assertTrue(party['bHidden']); self.assertTrue(other_enemy['bHidden'])
        self.assertFalse(vision['bHidden']); self.assertFalse(target['bHidden'])
        self.assertEqual(previously_hidden['Tags'], [])
        self.run_cooked(restore, actors, event, None)  # restoration survives a vanished vision
        self.assertFalse(party['bHidden']); self.assertFalse(other_enemy['bHidden'])
        self.assertTrue(previously_hidden['bHidden'])
        self.assertTrue(all(not a['Tags'] for a in actors if a is not None))
        self.run_cooked(restore, actors, event, None)  # idempotent cleanup

    def test_invalid_fields_return_clean_cli_error(self):
        bad = copy.deepcopy(self.events[0]); bad['NativeStageVisibility_UnitId'] = 0
        result = self.patch([{'asset': 'shell', 'export': self.ids[0], 'set': bad}])
        self.assertEqual(result.returncode, 1)
        self.assertIn('NativeStageVisibility requires', result.stderr)
        self.assertNotIn('Unhandled exception', result.stderr)


if __name__ == '__main__': unittest.main()
