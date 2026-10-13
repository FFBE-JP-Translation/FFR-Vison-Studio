"""Focused integration checks executed against the installed project modules."""
from copy import deepcopy
from pathlib import Path
import json
import hashlib
import math
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tools/devui'),str(ROOT/'tools/tests')]
import ffbe_attack_director as director
import ffbe_presentation as presentation
import ffbe_resonance as resonance
import ffbe_cast_camera as cast_camera
from tools.tests import test_ffbe_native_participant_focus as focus
from tools.tests.fixtures.participant_camera_vm import CameraVM, vector
from tools.tests.test_ffbe_native_resonance_visibility import NativeResonanceVisibility


class ScheduleTests(unittest.TestCase):
    def entry(self,lb=True):
        return {'_hostVisionUnitId':13503,'_hostResonance':lb}

    def test_cast_camera_lb_waits_for_native_movement_before_attack(self):
        source=cast_camera.lb_source({'moveType':1,'hitFrames':[5,30]})
        plan=resonance.schedule(1,2,123,source)
        move=next(e for e in plan['events'] if e['set']['EventType']=='UnitMoveToTarget')
        attack=next(e for e in plan['events'] if e['set'].get('Unit_PlayAnimByName_AnimationName')=='LB1')
        self.assertGreater(attack['time'],move['time']+12*800)

    def test_moving_five_stages_preserve_hits_and_audio(self):
        source={'moveType':1,'hitFrames':[5,30]}
        sounds=[{'frame':30,'bank':'bank','cueName':'last','durationMs':100}]
        original=resonance.schedule(1,2,123,source,sounds)
        plan=director.direct(original,self.entry(),director.DEFAULTS,visual_end=30000)
        events=plan['events']
        for kind in ('OtherReaction','SoundPlayHitSound'):
            self.assertEqual([e for e in original['events'] if e['set']['EventType']==kind],
                             [e for e in events if e['set']['EventType']==kind])
        cameras=[e for e in events if e['set']['EventType']=='NativeParticipantCamera']
        self.assertTrue(all(e['set']['NativeParticipantCamera_Shot']=='caster' for e in cameras))
        move=next(e for e in events if e['set']['EventType']=='NativeGroundApproach')
        self.assertLess(cameras[0]['time'],move['time'])
        arrival=move['time']+move['set']['NativeGroundApproach_Frame']*800
        self.assertGreaterEqual(cameras[-1]['time'],arrival)
        self.assertTrue(all(b['time']-a['time'] >= a['set']['NativeParticipantCamera_Frame']*800
                            for a,b in zip(cameras,cameras[1:])))
        self.assertEqual(move['set']['NativeGroundApproach_Offset']['z'],0)
        returning=next(e for e in events if e['set']['EventType']=='UnitMoveToDefaultLocation')
        aura_restore=next(e for e in events if e['set'].get('NativeAura_IsVisible') is True)
        self.assertGreater(aura_restore['time'],returning['time']+returning['set']['Unit_MoveToDefaultLocation_Frame']*800)
        isolation=[e for e in events if e['set']['EventType']=='NativeResonanceVisibility']
        self.assertEqual(len(isolation),2)
        self.assertTrue(all(e['set']['NativeResonanceVisibility_HideAura'] is False for e in isolation))
        self.assertLess(max(e['time'] for e in events),plan['duration'])

    def test_stationary_ordinary_ability_holds_cast_focus_until_cleanup(self):
        original=resonance.schedule(1,1,123,{'moveType':0,'hitFrames':[15]})
        plan=director.direct(original,self.entry(False),director.DEFAULTS)
        events=plan['events']; kinds=[e['set']['EventType'] for e in events]
        self.assertNotIn('NativeAuraVisibility',kinds)
        self.assertNotIn('NativeResonanceVisibility',kinds)
        self.assertNotIn('NativeGroundApproach',kinds)
        start=presentation.action_start(plan)
        self.assertTrue(any(e['time']>start and e['set']['EventType']=='CameraSetDefault' for e in events))
        self.assertFalse(any(e['time']==start and e['set']['EventType']=='CameraSetDefault' for e in events))
        self.assertEqual([e['set']['NativeParticipantCamera_Shot'] for e in events if e['set']['EventType']=='NativeParticipantCamera'],['caster'])
        self.assertEqual(next(e['set']['NativeParticipantCamera_Frame'] for e in events if e['set']['EventType']=='NativeParticipantCamera'),10)

    def test_ordinary_moving_action_hides_aura_without_isolation(self):
        original=resonance.schedule(1,1,123,{'moveType':1,'hitFrames':[15]})
        plan=director.direct(original,self.entry(False),director.DEFAULTS)
        self.assertEqual(sum(e['set']['EventType']=='NativeAuraVisibility' for e in plan['events']),2)
        self.assertFalse(any(e['set']['EventType']=='NativeResonanceVisibility' for e in plan['events']))

    def test_invalid_values_rejected(self):
        for setting in ({'castZoom':float('nan')},{'castZoom':0},{'panFrames':2.5},{'camera':1},
                        {'layers':{'one':{'scale':float('inf')}}},{'layers':{'one':{'anchor':'filesystem'}}}):
            with self.assertRaises(ValueError): director.validate(setting)

    def test_portable_defaults_and_move_overrides(self):
        entry={'reconstructionProfile':{'attackDirector':{'castZoom':1.8}}}
        doc={'defaults':{'actionZoom':1.2},'moves':{'123':{'GL/ability/1':{'castZoom':2.1}}}}
        values=director.resolve('123','GL/ability/1',entry,doc)
        self.assertEqual(values['castZoom'],2.1); self.assertEqual(values['actionZoom'],1.2)
        untouched=deepcopy(entry); director.configure(entry,values); self.assertEqual(entry,untouched)


class AttackCamera(focus.NativeParticipantFocus):
    # Borrow fixture utilities, not its assertions for the previous zoom range.
    def test_invalid_zoom_factor_is_not_reinterpreted_as_focal_mm(self):
        for value in (True,.49,3.01,32.5,float('nan')):
            op=deepcopy(self.ops[0]); op['set']['NativeParticipantCamera_ZoomFactor']=value
            result=self.patch([op]); self.assertNotEqual(result.returncode,0)

    def test_new_participant_union_includes_caster_and_all_targets(self):
        op=deepcopy(self.ops[1]); op['set']['NativeParticipantCamera_Shot']='participants'
        result=self.patch([op]); self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        document=self.dump('tojson'); decoded=self.dump('seqdump')
        self.assertEqual(next(v for k,v in decoded.items() if k.startswith(self.identifiers[1]+':')),op['set'])
        fn=document['Exports'][int(self.identifiers[1])-1]
        caster=focus.unit((0,750,0),160); targets=[focus.unit((0,-800,0),500),focus.unit((0,-400,0),400)]
        vm=CameraVM(document,fn,self.vm_size,caster,targets,focus.camera(),(1280,720))
        calls=vm.run(); self.assertEqual(vm.values['FFBE_Focus_Count'],3)
        self.assertEqual(len(calls),2); self.assertGreater(calls[1][27],0)
        self.patch([self.ops[1]])

    def test_destination_matches_ground_endpoint_and_native_zoom(self):
        op=deepcopy(self.ops[0]); op['set'].update(NativeParticipantCamera_Shot='destination',
            NativeParticipantCamera_DestinationOffset={'x':0.,'y':250.,'z':0.},NativeParticipantCamera_DestinationPart='Null_root')
        result=self.patch([op]); self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        document=self.dump('tojson'); decoded=self.dump('seqdump')
        self.assertEqual(next(v for k,v in decoded.items() if k.startswith(self.identifiers[0]+':')),op['set'])
        caster=focus.unit((0,800,10),160); target=focus.unit((0,-500,0),500)
        target['m_pSsPlayerComponent']['sockets']['Null_root']=focus.xyz((0,-500,20))
        class VM(CameraVM):
            def evaluate(self,node,context=None):
                if self.kind(node) in ('EX_CallMath','EX_FinalFunction') and self.document['Imports'][-node['StackNode']-1]['ObjectName']=='Multiply_VectorVector':
                    a,b=[vector(self.evaluate(n,context)) for n in node['Parameters']]
                    return dict(zip(('X','Y','Z'),a*b))
                return super().evaluate(node,context)
        # Roundtrip proves the new params survive cooking; actual projection is checked through the shared VM below.
        fn=document['Exports'][int(self.identifiers[0])-1]
        vm=VM(document,fn,self.vm_size,caster,[target],focus.camera(),(1280,720))
        calls=vm.run()
        self.assertAlmostEqual(vm.values['FFBE_Focus_Feet']['Y'],-250.)
        self.assertAlmostEqual(vm.values['FFBE_Focus_Feet']['Z'],10.)
        self.assertAlmostEqual(calls[1][27],32.5*1.25)
        self.patch([self.ops[0]])


class SeparateAuraPolicy(NativeResonanceVisibility):
    def test_isolation_without_aura_changes_roundtrips(self):
        op=deepcopy(self.op)
        op['set']['NativeResonanceVisibility_HideAura']=False
        result=self.patch([op])
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        decoded=self.dump('seqdump')
        self.assertEqual(next(v for k,v in decoded.items() if k.startswith(self.identifier+':')),op['set'])
        doc=self.dump('tojson')
        code=doc['Exports'][int(self.identifier)-1]['ScriptBytecode']
        calls=[doc['Imports'][-e['StackNode']-1]['ObjectName'] for e in self.walk(code) if 'StackNode' in e]
        self.assertIn('Array_Contains',calls)
        self.assertIn('SetActorHiddenInGame',calls)
        self.assertNotIn('GetAsset',calls)
        self.assertNotIn('SetHiddenInGame',calls)


class PreparedEditTests(unittest.TestCase):
    def test_transform_copies_media_and_preserves_original_and_flashes(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work); source=root/'source'; source.mkdir()
            spec={'animePackName':'original','runtimeViewport':{'width':1280},
                  'model':{'parts':[{'name':'root'}]},'animations':[
                      {'isSetup':True,'parts':{}},
                      {'parts':{'root':{'Posx':[[0,10],[20,30]],'Sclx':[[0,1]]}}}]}
            raw=json.dumps(spec).encode(); (source/'spec.json').write_bytes(raw)
            (source/'page.raw').write_bytes(b'pixels')
            checks={n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in ('spec.json','page.raw')}
            fx={'name':'original','layer':2,'anchor':'screen','spec':'source','checksums':checks,'frame':0}
            entry={'visuals':[fx,{**fx,'name':'flash','layer':1}]}
            values=director.validate({'scale':2.,'offsetX':12.,'offsetY':-8.,'layers':{'flash:1':{'depth':-80.}}})
            output=director.materialize(entry,values,root)
            rear,front=output['visuals']
            self.assertEqual(rear['anchor'],'target_group'); self.assertEqual(rear['_directorDepth'],40.)
            self.assertEqual(front['anchor'],'screen'); self.assertEqual(front['_directorDepth'],-80.)
            self.assertEqual(front['placement']['mode'],'camera_plane')
            self.assertEqual(front['placement']['cameraDepth']['front'],88.)
            updated=json.loads((root/rear['spec']/'spec.json').read_bytes())
            self.assertNotIn('runtimeViewport',updated)
            self.assertEqual(updated['animations'][0]['parts']['root']['Sclx'],[[0,2.]])
            self.assertEqual(updated['animations'][1]['parts']['root']['Posx'],[[0,22.],[20,42.]])
            self.assertEqual((source/'spec.json').read_bytes(),raw)
            self.assertEqual((root/rear['spec']/'page.raw').read_bytes(),b'pixels')


if __name__=='__main__': unittest.main(verbosity=2)
