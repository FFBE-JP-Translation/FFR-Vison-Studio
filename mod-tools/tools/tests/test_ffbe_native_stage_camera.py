"""Native stage-camera adapter: real cooked VM structure and corruption rejection."""
import copy
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import test_ffbe_native_aura as aura_tests
import ffbe_resonance as resonance
import make_vision_mod as generator

class NativeStageCameraCooked(unittest.TestCase):
    command=classmethod(aura_tests.NativeAuraCooked.command.__func__)
    dump=classmethod(aura_tests.NativeAuraCooked.dump.__func__)
    patch=classmethod(aura_tests.NativeAuraCooked.patch.__func__)
    kind=staticmethod(aura_tests.NativeAuraCooked.kind)

    @classmethod
    def setUpClass(cls):
        source=Path(generator.LEGACY)/(resonance.SHELL+'.uasset')
        if not source.is_file():raise unittest.SkipTest('Native battle shell unavailable')
        cls.temp=tempfile.TemporaryDirectory(prefix='native-stage-camera-',dir=ROOT/'build')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work=Path(cls.temp.name);cls.asset=cls.work/'shell.uasset'
        cls.usmap=cls.work/'Mappings.usmap';shutil.copy2(generator.USMAP,cls.usmap)
        for suffix in ('.uasset','.uexp','.ubulk'):
            if source.with_suffix(suffix).exists():shutil.copy2(source.with_suffix(suffix),cls.asset.with_suffix(suffix))
        dump=cls.dump('seqdump')
        cls.identifier=next(k.split(':')[0] for k,v in dump.items() if isinstance(v,dict) and v.get('$struct')=='BTL_SEQUENCE_PARAMETER')
        cls.event={'EventType':'NativeStageCamera','NativeStageCamera_UnitId':13503,
                   'NativeStageCamera_AddLocation':{'x':0.0,'y':-268.8,'z':235.2}}
        cls.op={'asset':'shell','export':cls.identifier,'set':cls.event}
        result=cls.patch([cls.op])
        if result.returncode:raise AssertionError(result.stdout+result.stderr)

    @staticmethod
    def walk(e):
        if isinstance(e,dict):
            if '$type' in e and '.Expressions.' in e['$type']:yield e
            for v in e.values():yield from NativeStageCameraCooked.walk(v)
        elif isinstance(e,list):
            for v in e:yield from NativeStageCameraCooked.walk(v)

    @classmethod
    def vm_size(cls,e):
        k=cls.kind(e)
        if k in ('EX_True','EX_False','EX_IntZero','EX_NoObject','EX_Nothing','EX_EndOfScript'):return 1
        if k in ('EX_IntConst','EX_FloatConst'):return 5
        if k in ('EX_ByteConst','EX_IntConstByte'):return 2
        if k in ('EX_DoubleConst','EX_ObjectConst','EX_InstanceVariable','EX_LocalVariable'):return 9
        if k=='EX_NameConst':return 13
        if k=='EX_StringConst':return len(e['Value'].encode('ascii'))+2
        if k=='EX_VectorConst':return 25
        if k=='EX_RotationConst':return 25
        if k in ('EX_CallMath','EX_FinalFunction'):return 10+sum(map(cls.vm_size,e['Parameters']))
        if k=='EX_LocalVirtualFunction':return 14+sum(map(cls.vm_size,e['Parameters']))
        if k=='EX_ArrayGetByRef':return 1+cls.vm_size(e['ArrayVariable'])+cls.vm_size(e['ArrayIndex'])
        if k=='EX_ArrayConst':return 14+sum(map(cls.vm_size,e['Elements']))
        if k=='EX_SoftObjectConst':return 1+cls.vm_size(e['Value'])
        if k=='EX_StructConst':return 14+sum(map(cls.vm_size,e['Value']))
        if k=='EX_Context_FailSilent':return 13+cls.vm_size(e['ObjectExpression'])+cls.vm_size(e['ContextExpression'])
        if k=='EX_JumpIfNot':return 5+cls.vm_size(e['BooleanExpression'])
        if k=='EX_Return':return 1+cls.vm_size(e['ReturnExpression'])
        raise AssertionError('Unexpected instruction '+k)

    def test_native_camera_call_and_bound_target_math(self):
        data=self.dump('tojson');fn=data['Exports'][int(self.identifier)-1];code=fn['ScriptBytecode'];imports=data['Imports']
        def resolve(i):self.assertLess(i,0);return imports[-i-1]
        def name(e):
            f=resolve(e['StackNode']);o=resolve(f['OuterIndex'])
            return resolve(o['OuterIndex'])['ObjectName'],o['ObjectName'],f['ObjectName']
        self.assertEqual([self.kind(e) for e in code],['EX_JumpIfNot']*5+['EX_LocalVirtualFunction','EX_Return','EX_EndOfScript'])
        size=sum(map(self.vm_size,code));end=sum(map(self.vm_size,code[:6]))
        self.assertEqual(fn['ScriptBytecodeSize'],size)
        self.assertEqual([e['CodeOffset'] for e in code[:5]],[end]*5)
        call=code[5];self.assertEqual(call['VirtualFunctionName'],'SeqBattleEvent')
        self.assertEqual(self.kind(call['Parameters'][0]),'EX_LocalVariable')
        self.assertEqual(call['Parameters'][0]['Variable']['New']['ResolvedOwner'],int(self.identifier))
        self.assertEqual(call['Parameters'][0]['Variable']['New']['Path'],[fn['LoadedProperties'][0]['Name']])
        sc=call['Parameters'][1];self.assertEqual(resolve(sc['Struct'])['ObjectName'],'BTL_SEQUENCE_PARAMETER')
        self.assertEqual(sc['StructSize'],3896);self.assertEqual(sc['Value'][0]['Value'],4)
        self.assertEqual(sc['Value'][15]['Value'],0) # native look-at duration
        self.assertEqual(sc['Value'][19]['Value'],-1) # actor target, never point-row ID
        sub=sc['Value'][14];self.assertEqual(name(sub),('/Script/Engine','KismetMathLibrary','Subtract_VectorVector'))
        add=sub['Parameters'][0];self.assertEqual(name(add),('/Script/Engine','KismetMathLibrary','Add_VectorVector'))
        self.assertEqual(add['Parameters'][1]['Value']['X'], '+0')
        self.assertAlmostEqual(float(add['Parameters'][1]['Value']['Y']),-268.8)
        self.assertAlmostEqual(float(add['Parameters'][1]['Value']['Z']),235.2)
        unit_loc=add['Parameters'][0];target_loc=sub['Parameters'][1]
        for e in (unit_loc,target_loc):self.assertEqual(name(e['ContextExpression']),('/Script/Engine','Actor','K2_GetActorLocation'))
        unit=unit_loc['ObjectExpression'];self.assertEqual(name(unit),('/Script/mucha','CPP_BFL_Battle','GetBattleUnitByUnitIdWithVision'))
        self.assertEqual(unit['Parameters'][0]['Value'],13503);self.assertEqual(self.kind(unit['Parameters'][1]),'EX_False')
        target=target_loc['ObjectExpression'];self.assertEqual(self.kind(target),'EX_ArrayGetByRef');self.assertEqual(self.kind(target['ArrayIndex']),'EX_IntZero')
        target_array=target['ArrayVariable']['ContextExpression']['Variable']['New']
        self.assertEqual(target_array['Path'],['m_TargetUnitList']);self.assertEqual(resolve(target_array['ResolvedOwner'])['ObjectName'],'CPP_BtlSequencerEvent')
        for expression in self.walk(code):
            if self.kind(expression)=='EX_Context_FailSilent':self.assertEqual(expression['Offset'],self.vm_size(expression['ContextExpression']))
        result=next(v for k,v in self.dump('seqdump').items() if k.split(':')[0]==self.identifier)
        self.assertEqual(result,self.event)

    def test_rejects_bad_fields_or_unbound_donor(self):
        bad=[]
        for value in (None,True,0,-1,2147483648,13503.5,'13503'):
            x=copy.deepcopy(self.op);x['set']['NativeStageCamera_UnitId']=value;bad.append(x)
        for value in (None,{}, {'x':0,'y':0}, {'x':0,'y':0,'z':0,'extra':1}, {'x':True,'y':0,'z':0}, {'x':'0','y':0,'z':0}):
            x=copy.deepcopy(self.op);x['set']['NativeStageCamera_AddLocation']=value;bad.append(x)
        for field,value in (('export','*'),('match',{})):
            x=copy.deepcopy(self.op);x[field]=value;bad.append(x)
        x=copy.deepcopy(self.op);x['set']['Camera_SetLookAtTarget_Id']=0;bad.append(x)
        for op in bad:
            with self.subTest(op=op):
                result=self.patch([op]);self.assertNotEqual(result.returncode,0)
                self.assertIn('NativeStageCamera',result.stdout+result.stderr)

    def test_corrupt_guard_is_rejected_on_readback(self):
        code=self.dump('tojson')['Exports'][int(self.identifier)-1]['ScriptBytecode'];end=code[0]['CodeOffset']
        asset=self.work/'corrupted.uasset'
        for suffix in ('.uasset','.uexp','.ubulk'):
            source=self.asset.with_suffix(suffix)
            if source.exists():shutil.copy2(source,asset.with_suffix(suffix))
        payload=asset.with_suffix('.uexp');raw=payload.read_bytes();marker=struct.pack('<BI',0x07,end)
        self.assertEqual(raw.count(marker),5)
        offset=raw.index(marker);payload.write_bytes(raw[:offset+1]+struct.pack('<I',end-1)+raw[offset+5:])
        result=self.command('seqdump',asset,self.work/'corrupted-seqdump.json')
        self.assertNotEqual(result.returncode,0);self.assertIn('Malformed NativeStageCamera guards',result.stdout+result.stderr)


    def test_stale_native_target_id_is_rejected_on_readback(self):
        # This adapter must use actor-root mode (-1), never a fixed target row.
        code=self.dump('tojson')['Exports'][int(self.identifier)-1]['ScriptBytecode']
        asset=self.work/'stale-target.uasset'
        for suffix in ('.uasset','.uexp','.ubulk'):
            source=self.asset.with_suffix(suffix)
            if source.exists():shutil.copy2(source,asset.with_suffix(suffix))
        payload=asset.with_suffix('.uexp');raw=payload.read_bytes()
        start=raw.index(struct.pack('<BI',0x07,code[0]['CodeOffset']))
        # Frame0, easing0, blend0, steps0, ID-1 in the canonical native struct.
        marker=b'\x1d'+struct.pack('<i',0)+b'\x24\x00\x1e'+struct.pack('<f',0)+b'\x1d'+struct.pack('<i',0)+b'\x1d'+struct.pack('<i',-1)
        at=raw.index(marker,start)+len(marker)-4
        payload.write_bytes(raw[:at]+struct.pack('<i',0)+raw[at+4:])
        result=self.command('seqdump',asset,self.work/'stale-target-seqdump.json')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Malformed NativeStageCamera guards',result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
