from pathlib import Path
from copy import deepcopy
import json, sys, tempfile, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ffbe_presentation as p
import convert_all_ffbe_animations as bulk
from ffbe_effects.playback_policy import configure
from ffbe_effects.regional_assets import choose
from ability_converter.commands import schedule

class PlaybackPolicy(unittest.TestCase):
    def test_ultima_lifts_only_the_blast_not_the_flash_or_background(self):
        entry={'visuals':[{'anchor':'screen','layer':1,'frame':41},
                           {'anchor':'screen','layer':1,'frame':40},
                           {'anchor':'screen','layer':2,'frame':40}]}
        result=configure(entry,'401007407','GL_2024/magic/20440')
        self.assertEqual(result['visuals'][0]['viewportRise'],.12)
        self.assertTrue(all('viewportRise' not in fx for fx in result['visuals'][1:]))
        self.assertNotIn('viewportRise',entry['visuals'][0])
    def test_portable_camera_precedes_art_and_keeps_each_source_clock(self):
        source={'supported':True,'timeline':{'hitFrames':[20,30],'moveType':0},'set':{}}
        plan=schedule(source,700,1.,'magic_attack',cast_frames=10,cast_motion='command')
        visual={'name':'test','asset':'/Game/test','partName':'root','anchor':'each_target',
                'layer':1,'frame':5,'frames':45,'sourceCoordinates':{'binding':'actor_root_snapshot',
                'offsetsApplied':True,'owner':'target','sampleFrame':5,'rectangleMode':'test'}}
        entry=configure({'sourceKey':'GL_2024/ability/12','visuals':[visual],
                         'targetType':'Single'},'123','GL_2024/ability/12')
        entry['_hostVisionUnitId']=7777
        sounds=[{'frame':-9,'role':'casting','bank':'opening','cueName':'cast','durationMs':100},
                {'frame':20,'bank':'action','cueName':'hit','durationMs':80}]
        before=deepcopy(entry)
        result=p.apply(plan,entry,sounds,700)
        origin=p.action_start(result)
        hits=[e['time']-origin for e in result['events'] if e['set']['EventType']=='OtherReaction']
        self.assertEqual(hits,[20*400,30*400])
        spawned=next(e for e in result['events'] if e['set']['EventType']=='SsActorSpawnSpriteStudioActor')
        self.assertEqual(spawned['time'],origin+5*400)
        shot=next(e for e in result['events'] if e['set'].get('NativeParticipantCamera_Shot')=='participants_zoom')
        self.assertEqual(origin,shot['time']+6*800)
        audio=[e for e in result['events'] if e['set']['EventType']=='SoundPlayHitSound']
        self.assertEqual(len(audio),2)
        self.assertEqual(audio[-1]['time'],origin+20*400)
        self.assertEqual(audio[0]['time'],p.phase_start(result,'cast')+400)
        order=next(e['set'] for e in result['events'] if e['set']['EventType']=='NativeActorRootSnapshot')
        self.assertEqual(order['NativeActorRootSnapshot_SortLayer'],-1)
        self.assertEqual(entry,before)

    def test_inventory_excludes_passives_and_reports_missing_forms(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);native=root/'data/ffbe/native_kits';native.mkdir(parents=True)
            catalog=root/'catalog.json';catalog.write_text(json.dumps([{'id':'10','forms':['11','12']}]))
            (native/'11.json').write_text(json.dumps({'kit':{'entries':[
                {'kind':'PASSIVE','status':'ready','sourceKey':'passive'},
                {'kind':'ABILITY','status':'ready','sourceKey':'active'},
                {'kind':'LB','status':'held','sourceKey':'held'}]}}))
            report=bulk.plan(root,catalog,root/'units',root/'output')
            self.assertEqual(report['readyActiveMoveMemberships'],1)
            self.assertEqual(report['heldActiveMoveMemberships'],1)
            self.assertEqual(report['missingNativeKits'],1)
            self.assertEqual(report['missingUnitArchives'],2)
            self.assertFalse((root/'output').exists())
            with self.assertRaisesRegex(ValueError,'separate'):bulk.plan(root,catalog,root/'units',root/'units')

    def test_regional_conflicts_fail_instead_of_picking_arbitrary_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);a=root/'a';b=root/'b';a.write_bytes(b'GL');b.write_bytes(b'JP')
            with self.assertRaisesRegex(ValueError,'Conflicting'):choose('effect.bmb',{'effect.bmb':[a,b]},root)
            b.write_bytes(b'GL')
            self.assertEqual(choose('effect.bmb',{'effect.bmb':[a,b]},root),(a,'GL export'))
            with self.assertRaisesRegex(ValueError,'Unsafe'):choose('../escape',{},root)
            with self.assertRaises(FileNotFoundError):choose('missing.bmb',{},root)

if __name__=='__main__':unittest.main()
