"""Native aura suppression: finite schedule and real Kismet package readback."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from test_ffbe_target_stage import fixture, bytype, verify
import ffbe_presentation as presentation
import ffbe_resonance as resonance
import make_vision_mod as generator


def enabled_fixture():
    plan,entry=fixture()
    entry['_hostVisionUnitId']=13503
    entry['reconstructionProfile']['screenPlacement']['hideNativeAuras']=True
    for fx in entry['visuals']:
        if fx['anchor']=='screen':fx['placement']['hideNativeAuras']=True
    return plan,entry


class NativeAuraSchedule(unittest.TestCase):
    def test_pair_wraps_effects_and_actual_native_return(self):
        plan,entry=enabled_fixture()
        original=copy.deepcopy(plan)
        result=presentation.apply(plan,entry,[],7)
        pair=bytype(result,'NativeAuraVisibility')
        self.assertEqual(len(pair),2)
        self.assertEqual([e['NativeAura_IsVisible'] for _,e in pair],[False,True])
        self.assertEqual([e['NativeAura_UnitId'] for _,e in pair],[13503,13503])
        self.assertEqual(pair[0][0],min(t for t,_ in bytype(result,'SsActorSpawnSpriteStudioActor'))-1)
        return_ends=[t+e['Unit_MoveToDefaultLocation_Frame']*400 for t,e in bytype(result,'UnitMoveToDefaultLocation')]
        self.assertTrue(return_ends)
        self.assertGreater(pair[1][0],max(return_ends))
        self.assertLess(pair[1][0],result['duration'])
        self.assertEqual(bytype(plan,'OtherReaction'),bytype(result,'OtherReaction'))
        self.assertEqual(plan,original)
        self.assertTrue(verify(entry,result)['targetStageVerified'])

    def test_false_and_absent_leave_native_auras_unchanged(self):
        for flag in (None,False):
            plan,entry=fixture()
            if flag is not None:
                entry['reconstructionProfile']['screenPlacement']['hideNativeAuras']=flag
                for fx in entry['visuals']:
                    if fx['anchor']=='screen':fx['placement']['hideNativeAuras']=flag
            result=presentation.apply(plan,entry,[],7)
            self.assertFalse(bytype(result,'NativeAuraVisibility'))
            verify(entry,result)

    def test_bad_flag_or_mismatched_screen_layer_is_rejected(self):
        plan,entry=enabled_fixture()
        for value in (1,'true',None):
            bad=copy.deepcopy(entry);bad['reconstructionProfile']['screenPlacement']['hideNativeAuras']=value
            with self.assertRaises(ValueError):presentation.apply(plan,bad,[],7)
        entry['visuals'][0]['placement']['hideNativeAuras']=False
        with self.assertRaises(ValueError):presentation.apply(plan,entry,[],7)

    def test_missing_or_invalid_selected_vision_id_is_rejected(self):
        for value in (None, True, 0, -1, '13503'):
            plan,entry=enabled_fixture();entry['_hostVisionUnitId']=value
            with self.subTest(value=value), self.assertRaises(ValueError):
                presentation.apply(plan,entry,[],7)

    def test_independent_cooked_verifier_rejects_missing_or_early_restore(self):
        plan,entry=enabled_fixture();result=presentation.apply(plan,entry,[],7)
        bad=copy.deepcopy(result)
        bad['events']=[e for e in bad['events'] if not(e['set']['EventType']=='NativeAuraVisibility' and e['set']['NativeAura_IsVisible'])]
        with self.assertRaises(AssertionError):verify(entry,bad)
        bad=copy.deepcopy(result)
        restore=next(e for e in bad['events'] if e['set']['EventType']=='NativeAuraVisibility' and e['set']['NativeAura_IsVisible'])
        restore['time']-=400
        with self.assertRaises(AssertionError):verify(entry,bad)


class NativeAuraCooked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=Path(generator.LEGACY)/(resonance.SHELL+'.uasset')
        if not source.is_file():raise unittest.SkipTest('Native battle shell unavailable')
        cls.temp=tempfile.TemporaryDirectory(prefix='native-aura-',dir=ROOT/'build')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work=Path(cls.temp.name);cls.asset=cls.work/'shell.uasset'
        cls.usmap=cls.work/'Mappings.usmap';shutil.copy2(generator.USMAP,cls.usmap)
        for suffix in ('.uasset','.uexp','.ubulk'):
            if source.with_suffix(suffix).exists():shutil.copy2(source.with_suffix(suffix),cls.asset.with_suffix(suffix))
        dump=cls.dump('seqdump')
        cls.ids=[k.split(':')[0] for k,v in dump.items() if isinstance(v,dict) and v.get('$struct')=='BTL_SEQUENCE_PARAMETER'][:2]
        assert len(cls.ids)==2
        ops=[{'asset':'shell','export':i,'set':{'EventType':'NativeAuraVisibility','NativeAura_IsVisible':visible,
              'NativeAura_UnitId':13503}} for i,visible in zip(cls.ids,(False,True))]
        response=cls.patch(ops)
        if response.returncode:raise AssertionError(response.stdout+response.stderr)

    @classmethod
    def command(cls,*args):
        return subprocess.run([*generator.FFRDT,*map(str,args),'--usmap',cls.usmap],capture_output=True,text=True,encoding='utf-8')

    @classmethod
    def dump(cls,verb):
        path=cls.work/(verb+'.json');response=cls.command(verb,cls.asset,path)
        if response.returncode:raise AssertionError(response.stdout+response.stderr)
        return json.loads(path.read_text(encoding='utf-8-sig'))

    @classmethod
    def patch(cls,ops):
        path=cls.work/'patch.json';path.write_text(json.dumps({'legacyRoot':str(cls.work),'outRoot':str(cls.work),'tables':[],'bytecode':ops}))
        return cls.command('patch',path)

    @staticmethod
    def kind(expression):return expression['$type'].split('.')[-1].split(',')[0]

    @classmethod
    def vm_size(cls,e):
        """Independent native VM layout, deliberately not compiler sizing code."""
        k=cls.kind(e)
        if k in ('EX_True','EX_False','EX_IntZero','EX_Nothing','EX_EndOfScript'):return 1
        if k=='EX_IntConst':return 5
        if k in ('EX_ObjectConst','EX_InstanceVariable'):return 9
        if k in ('EX_CallMath','EX_FinalFunction'):return 10+sum(map(cls.vm_size,e['Parameters']))
        if k=='EX_ArrayGetByRef':return 1+cls.vm_size(e['ArrayVariable'])+cls.vm_size(e['ArrayIndex'])
        if k=='EX_StructMemberContext':return 9+cls.vm_size(e['StructExpression'])
        if k=='EX_Context_FailSilent':return 13+cls.vm_size(e['ObjectExpression'])+cls.vm_size(e['ContextExpression'])
        if k=='EX_JumpIfNot':return 5+cls.vm_size(e['BooleanExpression'])
        if k=='EX_Return':return 1+cls.vm_size(e['ReturnExpression'])
        raise AssertionError('Unexpected instruction '+k)

    def test_real_package_guarded_component_access_and_vm_offsets(self):
        data=self.dump('tojson');functions=self.dump('seqdump');imports=data['Imports']
        def resolve(index):
            self.assertLess(index,0);return imports[-index-1]
        def function(e,package,owner,name):
            f=resolve(e['StackNode']);self.assertEqual(f['ObjectName'],name)
            o=resolve(f['OuterIndex']);self.assertEqual(o['ObjectName'],owner)
            self.assertEqual(resolve(o['OuterIndex'])['ObjectName'],package)
        def unit(e):
            self.assertEqual(self.kind(e),'EX_CallMath')
            function(e,'/Script/mucha','CPP_BFL_Battle','GetBattleUnitByUnitIdWithVision')
            self.assertEqual(e['Parameters'][0]['Value'],13503)
            self.assertEqual(self.kind(e['Parameters'][1]),'EX_False')
        def property_(p,owner,name):
            self.assertEqual(p['New']['Path'],[name]);self.assertEqual(resolve(p['New']['ResolvedOwner'])['ObjectName'],owner)
        def context(e):
            self.assertEqual(self.kind(e),'EX_Context_FailSilent')
            self.assertEqual(e['Offset'],self.vm_size(e['ContextExpression']))
        def registry(e):
            context(e);unit(e['ObjectExpression'])
            self.assertEqual(self.kind(e['ContextExpression']),'EX_InstanceVariable')
            property_(e['ContextExpression']['Variable'],'CPP_BtlUnit','m_SsNiagaraDatas')
            property_(e['RValuePointer'],'CPP_BtlUnit','m_SsNiagaraDatas')
        def component(e):
            self.assertEqual(self.kind(e),'EX_StructMemberContext')
            property_(e['StructMemberExpression'],'SsNiagaraData','NiagaraComponent')
            self.assertEqual(resolve(e['StructMemberExpression']['New']['ResolvedOwner'])['ClassName'],'ScriptStruct')
            array=e['StructExpression'];self.assertEqual(self.kind(array),'EX_ArrayGetByRef')
            self.assertEqual(self.kind(array['ArrayIndex']),'EX_IntZero');registry(array['ArrayVariable'])
        for identifier,visible in zip(self.ids,(False,True)):
            fn=data['Exports'][int(identifier)-1];code=fn['ScriptBytecode']
            self.assertEqual([self.kind(e) for e in code],['EX_JumpIfNot']*4+['EX_Context_FailSilent','EX_Return','EX_EndOfScript'])
            self.assertEqual(fn['ScriptBytecodeSize'],322)
            self.assertEqual(sum(map(self.vm_size,code)),322)
            self.assertEqual([e['CodeOffset'] for e in code[:4]],[319]*4)
            valid=code[0]['BooleanExpression'];function(valid,'/Script/Engine','KismetSystemLibrary','IsValid');unit(valid['Parameters'][0])
            check=code[1]['BooleanExpression'];function(check,'/Script/Engine','KismetArrayLibrary','Array_IsValidIndex')
            registry(check['Parameters'][0]);self.assertEqual(self.kind(check['Parameters'][1]),'EX_IntZero')
            valid=code[2]['BooleanExpression'];function(valid,'/Script/Engine','KismetSystemLibrary','IsValid');component(valid['Parameters'][0])
            eq=code[3]['BooleanExpression'];function(eq,'/Script/Engine','KismetMathLibrary','EqualEqual_ObjectObject')
            assetctx=eq['Parameters'][0];context(assetctx);component(assetctx['ObjectExpression'])
            function(assetctx['ContextExpression'],'/Script/Niagara','NiagaraComponent','GetAsset')
            property_(assetctx['RValuePointer'],'GetAsset','ReturnValue')
            expected=resolve(eq['Parameters'][1]['Value'])
            self.assertEqual(expected['ObjectName'],'NS_EF_BTL_VisionAura_AuraOnly')
            self.assertEqual(expected['ClassName'],'NiagaraSystem');self.assertEqual(expected['ClassPackage'],'/Script/Niagara')
            self.assertEqual(resolve(expected['OuterIndex'])['ObjectName'],'/Game/Effect/04_BTL/VisionAura/NS_EF_BTL_VisionAura_AuraOnly')
            setter=code[4];context(setter);component(setter['ObjectExpression'])
            self.assertEqual(setter['RValuePointer']['New'],{'$type':'UAssetAPI.UnrealTypes.FFieldPath, UAssetAPI','Path':[],'ResolvedOwner':0})
            function(setter['ContextExpression'],'/Script/Engine','SceneComponent','SetVisibility')
            self.assertEqual([self.kind(e) for e in setter['ContextExpression']['Parameters']],['EX_True' if visible else 'EX_False','EX_True'])
            self.assertEqual(self.kind(code[5]['ReturnExpression']),'EX_Nothing')
            actual=next(v for k,v in functions.items() if k.split(':')[0]==identifier)
            self.assertEqual(actual,{'EventType':'NativeAuraVisibility','NativeAura_UnitId':13503,'NativeAura_IsVisible':visible})

    def test_native_adapter_rejects_invalid_scope_and_fields(self):
        valid={'asset':'shell','export':self.ids[0],'set':{'EventType':'NativeAuraVisibility','NativeAura_IsVisible':False,'NativeAura_UnitId':13503}}
        bad=[]
        for value in (None,True,0,-1,2147483648,13503.5,'13503'):
            x=copy.deepcopy(valid);x['set']['NativeAura_UnitId']=value;bad.append(x)
        x=copy.deepcopy(valid);del x['set']['NativeAura_UnitId'];bad.append(x)
        x=copy.deepcopy(valid);x['set']['NativeAura_IsVisible']=0;bad.append(x)
        x=copy.deepcopy(valid);x['set']['Unit_SetAlpha_Alpha']=0;bad.append(x)
        x=copy.deepcopy(valid);x['export']='*';bad.append(x)
        x=copy.deepcopy(valid);x['match']={};bad.append(x)
        for op in bad:
            with self.subTest(op=op):
                response=self.patch([op]);self.assertNotEqual(response.returncode,0)
                self.assertIn('NativeAuraVisibility',response.stdout+response.stderr)

    def test_reader_rejects_corrupted_native_jump_before_game_load(self):
        # Keep native UniversalObjectLocator private fields intact: corrupt
        # one fixed-width serialized jump in a byte-for-byte package copy.
        import struct
        asset=self.work/'corrupted.uasset'
        for suffix in ('.uasset','.uexp','.ubulk'):
            source=self.asset.with_suffix(suffix)
            if source.exists():shutil.copy2(source,asset.with_suffix(suffix))
        payload=asset.with_suffix('.uexp');raw=payload.read_bytes()
        marker=struct.pack('<BI',0x07,319) # EX_JumpIfNot + absolute VM return offset
        self.assertEqual(raw.count(marker),8) # four guards in each visibility function
        offset=raw.index(marker)
        raw=raw[:offset+1]+struct.pack('<I',318)+raw[offset+5:]
        payload.write_bytes(raw)
        result=self.command('seqdump',asset,self.work/'corrupted-seqdump.json')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('guards, field paths, offsets or asset identity',result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
