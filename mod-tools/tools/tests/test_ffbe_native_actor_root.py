"""Selected-vision root snapshots must never sample the mechanical owner."""
from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).resolve().parent)]
from tools.tests import test_ffbe_native_aura as aura
from tools.tests import test_ffbe_native_stage_camera as stage
import ffbe_resonance as resonance
import make_vision_mod as generator


class NativeActorRoot(unittest.TestCase):
    command=classmethod(aura.NativeAuraCooked.command.__func__)
    dump=classmethod(aura.NativeAuraCooked.dump.__func__)
    patch=classmethod(aura.NativeAuraCooked.patch.__func__)
    kind=staticmethod(aura.NativeAuraCooked.kind)
    walk=staticmethod(stage.NativeStageCameraCooked.walk)

    @classmethod
    def vm_size(cls,e):
        kind=cls.kind(e)
        if kind=='EX_Let':return 9+cls.vm_size(e['Variable'])+cls.vm_size(e['Expression'])
        if kind=='EX_StructMemberContext':return 9+cls.vm_size(e['StructExpression'])
        if kind=='EX_Jump':return 5
        return stage.NativeStageCameraCooked.vm_size.__func__(cls,e)

    @classmethod
    def setUpClass(cls):
        source=Path(generator.LEGACY)/(resonance.SHELL+'.uasset')
        if not source.is_file():raise unittest.SkipTest('Native shell unavailable')
        cls.temp=tempfile.TemporaryDirectory(prefix='native-actor-root-',dir=ROOT/'build')
        cls.addClassCleanup(cls.temp.cleanup);cls.work=Path(cls.temp.name);cls.asset=cls.work/'shell.uasset'
        cls.usmap=cls.work/'Mappings.usmap';shutil.copy2(generator.USMAP,cls.usmap)
        for suffix in ('.uasset','.uexp','.ubulk'):
            if source.with_suffix(suffix).exists():shutil.copy2(source.with_suffix(suffix),cls.asset.with_suffix(suffix))
        cls.identifier=next(k.split(':')[0] for k,v in cls.dump('seqdump').items() if isinstance(v,dict) and v.get('$struct')=='BTL_SEQUENCE_PARAMETER')
        cls.event={'EventType':'NativeActorRootSnapshot','NativeActorRootSnapshot_Id':'FFBE_444040_0',
            'NativeActorRootSnapshot_UnitId':13503,'NativeActorRootSnapshot_IsTarget':False,'NativeActorRootSnapshot_Depth':-8.}
        cls.op={'asset':'shell','export':cls.identifier,'set':cls.event}
        result=cls.patch([cls.op])
        if result.returncode:raise AssertionError(result.stdout+result.stderr)

    def test_caster_world_origin_resolves_vision_and_freezes_component(self):
        doc=self.dump('tojson');fn=doc['Exports'][int(self.identifier)-1];code=fn['ScriptBytecode']
        imports=doc['Imports'];named=lambda e:imports[-e['StackNode']-1]['ObjectName']
        calls=[e for e in self.walk(code) if 'StackNode' in e]
        setter=next(e for e in calls if named(e)=='K2_SetWorldLocation')
        point=setter['Parameters'][0];self.assertEqual(named(point),'Add_VectorVector')
        root=point['Parameters'][0];self.assertEqual(named(root['ContextExpression']),'K2_GetActorLocation')
        self.assertEqual(named(root['ObjectExpression']),'GetBattleUnitByUnitIdWithVision')
        self.assertEqual(root['ObjectExpression']['Parameters'][0]['Variable']['New']['Path'],['FFBE_Root_UnitId'])
        self.assertEqual(code[0]['Expression']['Value'],13503)
        self.assertEqual(code[2]['Expression']['Value'],-8.)
        absolute=next(e for e in calls if named(e)=='SetAbsolute')
        self.assertEqual([self.kind(p) for p in absolute['Parameters']],['EX_True','EX_False','EX_False'])
        self.assertEqual([self.kind(p) for p in setter['Parameters'][1:]],['EX_False','EX_LocalVariable','EX_True'])
        self.assertEqual(sum(map(self.vm_size,code)),fn['ScriptBytecodeSize'])
        for expr in self.walk(code):
            if self.kind(expr)=='EX_Context_FailSilent':self.assertEqual(expr['Offset'],self.vm_size(expr['ContextExpression']))
        namecheck=next(e for e in calls if named(e)=='EqualEqual_NameName')
        self.assertEqual(namecheck['Parameters'][1]['Value'],'FFBE_444040_0')
        self.assertEqual(namecheck['Parameters'][0]['StructMemberExpression']['New']['Path'],['spriteStudioID'])
        self.assertFalse(any('m_ActionUnit' in str(e) for e in code))
        decoded=next(v for k,v in self.dump('seqdump').items() if k.startswith(self.identifier+':'))
        self.assertEqual(decoded,self.event)

    def test_bad_contract_rejected_before_mutation(self):
        before=self.asset.read_bytes(),self.asset.with_suffix('.uexp').read_bytes()
        for key,value in [('NativeActorRootSnapshot_UnitId',0),('NativeActorRootSnapshot_UnitId',True),
                          ('NativeActorRootSnapshot_Id','../bad'),('NativeActorRootSnapshot_IsTarget',1),
                          ('NativeActorRootSnapshot_Depth',float('inf'))]:
            op=deepcopy(self.op);op['set'][key]=value
            result=self.patch([op]);self.assertNotEqual(result.returncode,0)
        self.assertEqual(before,(self.asset.read_bytes(),self.asset.with_suffix('.uexp').read_bytes()))

    def test_corrupted_absolute_location_flag_is_rejected(self):
        asset=self.work/'bad-frozen.uasset'
        for suffix in ('.uasset','.uexp','.ubulk'):
            if self.asset.with_suffix(suffix).exists():shutil.copy2(self.asset.with_suffix(suffix),asset.with_suffix(suffix))
        payload=asset.with_suffix('.uexp');raw=payload.read_bytes()
        marker=b'\x27\x28\x28\x16'
        self.assertEqual(raw.count(marker),1)
        payload.write_bytes(raw.replace(marker,b'\x28\x28\x28\x16',1))
        result=self.command('seqdump',asset,self.work/'bad-frozen.json')
        self.assertNotEqual(result.returncode,0);self.assertIn('Malformed NativeActorRootSnapshot',result.stdout+result.stderr)

    def test_target_owner_uses_selected_target_root(self):
        op=deepcopy(self.op);op['set']['NativeActorRootSnapshot_IsTarget']=True
        result=self.patch([op]);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        doc=self.dump('tojson');code=doc['Exports'][int(self.identifier)-1]['ScriptBytecode']
        calls=[e for e in self.walk(code) if 'StackNode' in e]
        named=lambda e:doc['Imports'][-e['StackNode']-1]['ObjectName']
        self.assertFalse(any(named(e)=='GetBattleUnitByUnitIdWithVision' for e in calls))
        point=next(e for e in calls if named(e)=='K2_SetWorldLocation')['Parameters'][0]
        target=point['Parameters'][0]['ObjectExpression']
        self.assertEqual(self.kind(target),'EX_ArrayGetByRef')
        self.assertEqual(target['ArrayVariable']['ContextExpression']['Variable']['New']['Path'],['m_TargetUnitList'])
        self.assertEqual(next(v for k,v in self.dump('seqdump').items() if k.startswith(self.identifier+':')),op['set'])

    def test_z_indexed_target_has_guard_and_hides_unused_instance(self):
        op=deepcopy(self.op)
        op['set'].update(NativeActorRootSnapshot_IsTarget=True, NativeActorRootSnapshot_TargetIndex=1)
        result=self.patch([op]); self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        self.assertEqual(op['set'],next(v for k,v in self.dump('seqdump').items() if k.startswith(self.identifier+':')))
        doc=self.dump('tojson'); code=doc['Exports'][int(self.identifier)-1]['ScriptBytecode']
        calls=[e for e in self.walk(code) if 'StackNode' in e]
        named=lambda e:doc['Imports'][-e['StackNode']-1]['ObjectName']
        hide=next(e for e in calls if named(e)=='SetVisibility')
        self.assertEqual('EX_False',self.kind(hide['Parameters'][0]))
        disabled=next(e for e in calls if named(e)=='SetComponentTickEnabled')
        self.assertEqual('EX_False',self.kind(disabled['Parameters'][0]))
        target=next(e for e in calls if named(e)=='K2_SetWorldLocation')['Parameters'][0]['Parameters'][0]['ObjectExpression']
        self.assertEqual(['FFBE_Root_TargetIndex'],target['ArrayIndex']['Variable']['New']['Path'])
        self.assertEqual(1,code[3]['Expression']['Value'])

    def test_body_anchor_and_foreground_order_roundtrip(self):
        op=deepcopy(self.op)
        op['set'].update(NativeActorRootSnapshot_IsTarget=True, NativeActorRootSnapshot_TargetIndex=1,
                         NativeActorRootSnapshot_HeightFraction=.4, NativeActorRootSnapshot_SortLayer=-1)
        try:
            result=self.patch([op]);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(op['set'],next(v for k,v in self.dump('seqdump').items() if k.startswith(self.identifier+':')))
            doc=self.dump('tojson');fn=doc['Exports'][int(self.identifier)-1]
            names=[doc['Imports'][-e['StackNode']-1]['ObjectName'] for e in self.walk(fn['ScriptBytecode']) if 'StackNode' in e]
            self.assertIn('GetSocketLocation',names)
            self.assertIn('DoesSocketExist',names)
            self.assertIn('GetScaledCapsuleHalfHeight',names)
            self.assertIn('SetTranslucentSortPriority',names)
            self.assertNotIn('K2_SetActorLocation',names) # Never move the target or caster.
            for value in (-.1,1.1,True):
                bad=deepcopy(op);bad['set']['NativeActorRootSnapshot_HeightFraction']=value
                self.assertNotEqual(self.patch([bad]).returncode,0)
        finally:
            self.patch([self.op])

    def test_sort_only_preserves_cast_attachment_and_placement(self):
        op=deepcopy(self.op)
        op['set'].update(NativeActorRootSnapshot_SortLayer=-1,NativeActorRootSnapshot_PreservePlacement=True)
        try:
            result=self.patch([op]);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(op['set'],next(v for k,v in self.dump('seqdump').items() if k.startswith(self.identifier+':')))
            doc=self.dump('tojson');code=doc['Exports'][int(self.identifier)-1]['ScriptBytecode']
            names=[doc['Imports'][-e['StackNode']-1]['ObjectName'] for e in self.walk(code) if 'StackNode' in e]
            self.assertIn('SetTranslucentSortPriority',names)
            self.assertNotIn('K2_SetWorldLocation',names)
            self.assertNotIn('SetAbsolute',names)
        finally:self.patch([self.op])


if __name__=='__main__':unittest.main()
