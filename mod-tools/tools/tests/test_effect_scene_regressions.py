"""Regressions for instance-local fitting and the source action clock."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/ffbe_effects'))
import prepare_vision as prepare
import scene


def plate(size=510, **fields):
    return {'tex':0, 'uv':[0,0,32,32], 'pos':[0,0],
            'scale':[size*2.4/32]*2, 'rot':0, 'alpha':1., 'blend':'mix', **fields}


def spawn(**fields):
    return {'file':'shared.bmb', 'groupId':'42', 'anchor':'screen', 'layer':2,
            'frame':0, 'scale':1., 'x':0, 'y':0, 'rotation':[0,0,0], **fields}


def texture(_):
    return Image.new('RGBA', (32,32), (20,40,80,255))


class InstanceSceneRegressions(unittest.TestCase):
    def test_composed_screen_camera_uses_source_clock_without_hidden_lead_frames(self):
        source=spawn(frame=20)
        docs={'shared.bmb':{'pixelsPerUnit':2.4,'textures':['plate.png'],
                           'frames':[[plate()]]*20}}
        camera={'sourceCenter':[0,0],'pan':[
            {'frame':20,'durationFrames':10,'sourceCenter':[100,0],'easing':'Linear'}]}
        adapters=prepare.screen_adapter.resolve(
            [{'groupIds':['42'],'sourceCenter':[0,0],'scale':1}], [source],
            {'sourceOffset':[0,0],'camera':camera}, None)
        first,doc=prepare.compose([source],docs,screen_camera_groups=adapters)
        self.assertEqual(20,first)
        self.assertEqual([[],[]],doc['frames'][:2])
        # Native playback begins two frames before first: visible frame 2 is
        # source frame 20, and must coincide with the beginning of this pan.
        for index,expected in ((2,0),(7,50),(12,100)):
            self.assertAlmostEqual(expected,doc['frames'][index][0]['pos'][0]/2.4)

    def test_cover_only_fits_the_detected_spawn_of_a_shared_source(self):
        doc={'pixelsPerUnit':2.4, 'textures':['plate.png'],
             'frames':[[plate(), plate(size=20, blend='add')]]*90}
        docs={'shared.bmb':doc}
        original=deepcopy(docs)
        selected=spawn()
        detected=scene.classify([selected], docs, texture, action_frames=90)
        spawns=[selected, spawn(anchor='caster'), spawn(layer=1),
                spawn(groupId='43'), spawn(frame=120)]
        bounds=[-550,-280,300,430]
        audit={}
        with patch.object(prepare.to_ss6, 'load_texture', texture):
            first, result=prepare.compose(spawns, docs, background_detection=detected,
                background_rectangle=bounds, background_audits=audit)
        self.assertEqual(0, first)
        self.assertEqual(original, docs)
        self.assertEqual(90, audit['shared.bmb']['spriteFrames'])
        self.assertGreater(audit['shared.bmb']['maxScale'], 1)
        for frame in result['frames'][2:92]:
            self.assertEqual(8, len(frame))
            self.assertLess(scene.cover_factor(frame[0], bounds, 2.4), 1)
            self.assertEqual(doc['frames'][0][1], frame[1])
            # Caster, front, and another group using the same BMB stay exact.
            for offset in (2,4,6):
                self.assertEqual(doc['frames'][0], frame[offset:offset+2])
        # Even the same group using the same BMB at a later start is separate.
        self.assertEqual(doc['frames'], result['frames'][122:212])

    def prepared_detection(self, cgs_name):
        class Captured(Exception):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            source_key='JP/lb/123/level/40'
            snapshot={'root':source_key, 'records':[]}
            native={'kit':{'name':'Fixture', 'entries':[
                {'kind':'LB', 'status':'ready', 'name':'Fixture', 'sourceKey':source_key}]},
                'profiles':{source_key:{'snapshot':snapshot}}}
            kit_path=root/'data/ffbe/native_kits/123.json'
            kit_path.parent.mkdir(parents=True)
            kit_path.write_text(json.dumps(native), encoding='utf-8')
            sprites=root/'sprites'
            sprites.mkdir()
            if cgs_name:
                # Action duration is 600, while the early particle lasts 180.
                (sprites/cgs_name).write_text('0,0,0,240\n1,0,0,360\n', encoding='utf-8')
            doc={'pixelsPerUnit':2.4, 'textures':['plate.png'], 'frames':[[plate()]]*180}
            data={'spawns':[spawn()], 'sounds':[], 'issues':[], 'motionType':0}
            default_profile=scene.default_profile
            captured={}
            calls=0

            def capture_profile(form, key, detection):
                nonlocal calls
                calls+=1
                if calls==2:
                    captured.update(detection)
                    raise Captured()
                return default_profile(form, key, detection)

            with patch.object(prepare, 'ROOT', root), patch.object(prepare, 'WORK', root/'work'), \
                    patch.object(prepare, 'timeline', return_value=data), \
                    patch.object(prepare, 'bake_source', return_value=(doc, {'issues':[]})), \
                    patch.object(prepare.render, 'TextureCache'), patch.object(prepare, 'AudioLibrary'), \
                    patch.object(prepare.ffbe_catalog, 'sprite_dir', return_value=str(sprites)), \
                    patch.object(prepare.ffbe_catalog, 'shift_info', return_value=None), \
                    patch.object(prepare.to_ss6, 'load_texture', texture), \
                    patch.object(scene, 'default_profile', side_effect=capture_profile):
                with self.assertRaises(Captured):
                    prepare.prepare(['123'], [source_key], detect_scene=True)
            return captured

    def test_public_prepare_uses_cgs_action_duration_for_short_early_plate(self):
        for spelling in ('unit_limitatk_cgs_123.csv', 'unit_limit_atk_cgs_123.csv'):
            with self.subTest(spelling=spelling):
                detected=self.prepared_detection(spelling)
                self.assertEqual(600, detected['actionFrames'])
                self.assertEqual('screen_overlay', detected['kind'])
                self.assertEqual([], detected['evidence'])
                self.assertEqual('sprites/'+spelling, detected['actionDurationSource'])

    def test_missing_action_clock_cannot_authorize_background_replacement(self):
        detected=self.prepared_detection(None)
        self.assertEqual('unresolved_screen', detected['kind'])
        self.assertIn('unavailable', detected['actionDurationSource'])


class FlatFlashCover(unittest.TestCase):
    bounds=[-680,-290,360,410]

    def test_large_flat_flash_covers_every_corner_without_changing_other_channels(self):
        frame=plate(size=600, blend='add', alpha=.23, color=[.3,.6,.8], rot=15)
        doc={'pixelsPerUnit':2.4, 'textures':['atlas.png'], 'frames':[[],[frame],[]]}
        original=deepcopy(doc)
        placed=spawn(anchor='caster', layer=1, x=17, y=-10, rotation=[0,0,12])
        # Selected UV cell is solid, while the rest of its atlas has gradients.
        atlas=Image.new('RGBA',(64,32))
        for x in range(64):
            for y in range(32):
                atlas.putpixel((x,y),(255,254,255,255) if x<32 else (x,y,80,255))
        result,audit=scene.cover_flat_flashes(doc,[placed],self.bounds,lambda _:atlas.copy())
        self.assertEqual(original,doc)
        self.assertEqual(1,audit['spriteFrames'])
        self.assertGreater(audit['maxScale'],1)
        self.assertEqual([],result['frames'][0])
        self.assertEqual([],result['frames'][2])
        fitted=result['frames'][1][0]
        self.assertLess(scene.cover_factor(scene.placed_sprite(fitted,placed,2.4),self.bounds,2.4),1)
        self.assertEqual({k:v for k,v in frame.items() if k!='scale'},
                         {k:v for k,v in fitted.items() if k!='scale'})
        self.assertAlmostEqual(fitted['scale'][0]/frame['scale'][0],
                               fitted['scale'][1]/frame['scale'][1])

    def test_small_gradient_ring_and_transparent_particles_are_unchanged(self):
        solid=Image.new('RGBA',(32,32),(255,255,255,255))
        gradient=solid.copy()
        ring=solid.copy()
        for x in range(32):
            for y in range(32):
                gradient.putpixel((x,y),(x*8,y*8,255,255))
                if (x-16)**2+(y-16)**2<100:
                    ring.putpixel((x,y),(255,255,255,0))
        transparent=Image.new('RGBA',(32,32),(255,255,255,210))
        for label,sprite,img in [('small',plate(size=32),solid),
                                 ('gradient',plate(size=600),gradient),
                                 ('ring',plate(size=600),ring),
                                 ('transparent',plate(size=600),transparent),
                                 ('offset',plate(size=600,pos=[1000,0]),solid)]:
            with self.subTest(label=label):
                doc={'textures':['texture.png'],'frames':[[sprite]]}
                original=deepcopy(doc)
                result,audit=scene.cover_flat_flashes(doc,[spawn()],self.bounds,lambda _:img.copy())
                self.assertEqual(original,doc)
                self.assertEqual(original,result)
                self.assertEqual(0,audit['spriteFrames'])
                self.assertEqual(1.,audit['maxScale'])

    def test_flat_flash_bounds_must_be_finite_and_ordered(self):
        for bounds in ([0,0,0,10], [0,0,10,float('inf')], [0,0,True,10]):
            with self.subTest(bounds=bounds),self.assertRaises(ValueError):
                scene.cover_flat_flashes({'frames':[]},[],bounds,texture)


if __name__=='__main__':
    unittest.main()
