"""Screen framing follows camera pans without retiming or changing source art."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ffbe_effects'))
import screen_adapter


class ScreenCamera(unittest.TestCase):
    def test_declared_pan_interpolation_and_terminal_hold(self):
        camera={'sourceCenter':[0,0],'pan':[
            {'frame':10,'durationFrames':20,'sourceCenter':[100,80],'easing':'EaseInOut'},
            {'frame':40,'durationFrames':10,'sourceCenter':[20,20],'easing':'Linear'}]}
        self.assertEqual([0,0],screen_adapter.camera_center(camera,0))
        self.assertEqual([50,40],screen_adapter.camera_center(camera,20))
        self.assertEqual([100,80],screen_adapter.camera_center(camera,35))
        self.assertEqual([60,50],screen_adapter.camera_center(camera,45))
        self.assertEqual([20,20],screen_adapter.camera_center(camera,60))

    def test_center_survives_runtime_stretch_without_altering_uv_alpha_or_source(self):
        spawn={'groupId':'42','anchor':'screen','scale':1.1}
        placement={'sourceOffset':[-96,84],'camera':{'sourceCenter':[-100,40]}}
        config=[{'groupIds':['42'],'sourceCenter':[0,-15],'scale':1.9}]
        adapter=screen_adapter.resolve(config,[spawn],placement,{'stretchX':1.5,'center':[-96,84]})['42']
        sprite={'pos':[0,-15*1.1*2.4],'scale':[2,3],'uv':[0,0,8,8],
                'rot':90,'alpha':.65,'color':[1,.8,.1],'blend':'add'}
        original=deepcopy(sprite)
        out=screen_adapter.transform(sprite,spawn,150,adapter)
        self.assertAlmostEqual(-100,out['pos'][0]/2.4*1.5-96)
        self.assertAlmostEqual(40,out['pos'][1]/2.4+84)
        self.assertEqual([3.8,5.699999999999999],out['scale'])
        self.assertEqual(original,sprite)
        for key in ('uv','rot','alpha','color','blend'):
            self.assertEqual(original[key],out[key])

    def test_caster_and_missing_camera_cannot_be_screen_adapters(self):
        config=[{'groupIds':['42'],'sourceCenter':[0,0],'scale':1.2}]
        with self.assertRaises(ValueError):
            screen_adapter.resolve(config,[],None,None)
        with self.assertRaises(ValueError):
            screen_adapter.resolve(config,[{'groupId':'42','anchor':'caster'}],
                                   {'camera':{'sourceCenter':[0,0]},'sourceOffset':[0,0]},None)

    def test_runtime_viewport_pivot_can_differ_from_the_source_offset(self):
        spawn={'groupId':'42','anchor':'screen','scale':1.}
        placement={'sourceOffset':[-96,84],'camera':{'sourceCenter':[-100,40],'pan':[
            {'frame':10,'durationFrames':20,'sourceCenter':[100,80],'easing':'Linear'}]}}
        config=[{'groupIds':['42'],'sourceCenter':[0,0],'scale':1.2}]
        viewport={'stretchX':1.5,'center':[25,60]}
        adapter=screen_adapter.resolve(config,[spawn],placement,viewport)['42']
        sprite={'pos':[0,0],'scale':[1,1]}
        for frame in (0,10,20,30,40):
            out=screen_adapter.transform(sprite,spawn,frame,adapter)
            world_x=viewport['center'][0]+viewport['stretchX']*(
                out['pos'][0]/2.4+placement['sourceOffset'][0]-viewport['center'][0])
            world_y=out['pos'][1]/2.4+placement['sourceOffset'][1]
            expected=screen_adapter.camera_center(placement['camera'],frame)
            self.assertAlmostEqual(expected[0],world_x)
            self.assertAlmostEqual(expected[1],world_y)

    def test_malformed_profiles_fail_before_composition(self):
        config=[{'groupIds':['42'],'sourceCenter':[0,0],'scale':1.2}]
        spawn={'groupId':'42','anchor':'screen','scale':1.}
        placement={'sourceOffset':[0,0],'camera':{'sourceCenter':[0,0]}}
        cases=[([None],placement,None), (config,True,None),
               (config,{**placement,'sourceOffset':[False,0]},None),
               (config,{**placement,'mode':'frozen_caster_plane'},None),
               (config,{**placement,'camera':{'sourceCenter':[0]}},None),
               (config,placement,True), (config,placement,{}),
               (config,placement,{'stretchX':True,'center':[0,0]}),
               (config,placement,{'stretchX':1.5,'center':[float('nan'),0]})]
        for pan in (None, [{}], [{'frame':1,'durationFrames':0,'sourceCenter':[0,0]}],
                    [{'frame':1,'durationFrames':2,'sourceCenter':[0,0],'easing':'Bogus'}],
                    [{'frame':1,'durationFrames':20,'sourceCenter':[0,0]},
                     {'frame':10,'durationFrames':5,'sourceCenter':[0,0]}]):
            cases.append((config,{**placement,'camera':{'sourceCenter':[0,0],'pan':pan}},None))
        for c,p,v in cases:
            with self.subTest(config=c,placement=p,viewport=v),self.assertRaises(ValueError):
                screen_adapter.resolve(c,[spawn],p,v)

    def test_source_center_receives_the_same_spawn_rotation_and_translation_as_art(self):
        spawn={'groupId':'42','anchor':'screen','scale':1.5,'rotation':[0,0,90],'x':10,'y':20}
        config=[{'groupIds':['42'],'sourceCenter':[20,30],'scale':1.2}]
        placement={'sourceOffset':[-96,84],'camera':{'sourceCenter':[-100,40]}}
        adapter=screen_adapter.resolve(config,[spawn],placement,{'stretchX':1.5,'center':[0,0]})['42']
        # The local source center (20,30), rotated 90 degrees and scaled 1.5,
        # lands at (-35,10) after FFBE's +down spawn offset becomes +up.
        sprite={'pos':[-35*2.4,10*2.4],'scale':[2,3]}
        result=screen_adapter.transform(sprite,spawn,0,adapter)
        self.assertAlmostEqual(-100,(result['pos'][0]/2.4-96)*1.5)
        self.assertAlmostEqual(40,result['pos'][1]/2.4+84)


if __name__=='__main__':
    unittest.main()
