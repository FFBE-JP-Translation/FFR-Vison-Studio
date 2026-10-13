"""Embedded viewport plates preserve source pixels/clock without moving rings."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'),str(ROOT/'tools/ffbe_effects')]
from ffbe_effects import prepare_vision as prepare
from ffbe_effects import scene


def sprite(tex=0, *, size=400, alpha=.4, pos=(170,-95), blend='add'):
    return {'tex':tex,'uv':[0,0,8,8],'scale':[size*2.4/8]*2,
            'pos':list(pos),'rot':15,'alpha':alpha,'blend':blend,
            'color':[.3,.5,.8],'flipX':False,'flipY':True}


def spawn(frame=0, *, anchor='caster',layer=1):
    return {'file':'fixture.bmb','groupId':'9','source':'GL_2024/ability/1',
            'frame':frame,'phase':'action','anchor':anchor,'layer':layer,
            'x':912,'y':-350,'scale':1.7,'rotation':[0,0,42],
            'hostCoordinates':{'binding':'actor_root_snapshot','owner':'caster',
                'sampleFrame':frame-10,'rectangleMode':'logical_position',
                'offsetsApplied':True,'sourceOffset':[413,-121],'groupKey':str(frame)}}


class ViewportFlashes(unittest.TestCase):
    def texture(self,name):
        if name=='solid': return Image.new('RGBA',(8,8),(71,59,150,255))
        im=Image.new('RGBA',(8,8),(255,255,255,255))
        if name=='ring': im.putpixel((4,4),(255,255,255,0))
        if name=='gradient': im.putpixel((0,0),(20,80,255,255))
        return im

    def test_shifted_rotated_scaled_source_plate_is_centered_and_channels_preserved(self):
        source={'pixelsPerUnit':2.4,'textures':['solid'],
                'frames':[[],[sprite(alpha=.25)],[sprite(alpha=.75)]]}
        original=deepcopy(source);dispatch=spawn(70)
        kept,flashes,audit=scene.split_viewport_flashes(source,dispatch,self.texture)
        self.assertEqual(source,original)
        self.assertEqual([[],[],[]],kept['frames'])
        self.assertEqual([71,72],audit['sourceFrames'])
        for fi in (1,2):
            a,b=source['frames'][fi][0],flashes['frames'][fi][0]
            self.assertEqual([0.,0.],b['pos']);self.assertEqual(0.,b['rot'])
            self.assertEqual([96.,96.],b['scale'])
            for field in ('tex','uv','alpha','color','blend','flipX','flipY'):
                self.assertEqual(a[field],b[field])

    def test_rings_gradients_small_art_and_rear_sources_stay_unchanged(self):
        source={'pixelsPerUnit':2.4,'textures':['solid','ring','gradient'],
                'frames':[[sprite(0,size=30),sprite(1),sprite(2)]]}
        original=deepcopy(source)
        kept,flashes,audit=scene.split_viewport_flashes(source,spawn(),self.texture)
        self.assertIsNone(flashes);self.assertEqual(original,kept)
        self.assertEqual(0,audit['spriteFrames'])
        rear={'pixelsPerUnit':2.4,'textures':['solid'],'frames':[[sprite()]]}
        kept,flashes,audit=scene.split_viewport_flashes(rear,spawn(anchor='screen',layer=2),self.texture)
        self.assertIsNone(flashes);self.assertEqual(rear,kept)

    def test_real_rf_blue_and_white_preserve_complete_opacity_sequences(self):
        path=ROOT/'build/ffbe-effects-catalog-work/decoded/85afe66d016aaedf/doc.json'
        if not path.is_file(): self.skipTest('Local decoded RF source is unavailable')
        doc=json.loads(path.read_text(encoding='utf-8'));original=deepcopy(doc)
        texture_root=ROOT/'build/effects/textures'
        kept,flashes,audit=scene.split_viewport_flashes(doc,spawn(),lambda n:Image.open(texture_root/n))
        blue='nativeuv__7dc1cc623fa744acf81a8482.png'
        white='nativeuv__4c5ed1b45a6bb80afbf39871.png'
        self.assertEqual([blue,white],audit['textures'])
        self.assertEqual(list(range(85,109))+list(range(273,313)),audit['sourceFrames'])
        self.assertEqual(64,audit['spriteFrames']);self.assertEqual(original,doc)
        for name,rgba,size in [(blue,(71,59,150,255),710),(white,(255,255,255,255),600)]:
            with Image.open(texture_root/name) as im:
                self.assertEqual((8,8),im.size)
                self.assertEqual({rgba},set(im.convert('RGBA').getdata()))
            source_parts=[(fi,s) for fi,f in enumerate(doc['frames']) for s in f if doc['textures'][s['tex']]==name]
            output_parts=[(fi,s) for fi,f in enumerate(flashes['frames']) for s in f if flashes['textures'][s['tex']]==name]
            self.assertEqual([fi for fi,_ in source_parts],[fi for fi,_ in output_parts])
            for (fi,a),(_,b) in zip(source_parts,output_parts):
                self.assertAlmostEqual(size,a['scale'][0]*a['uv'][2]/2.4)
                self.assertEqual([0.,0.],b['pos'])
                for field in ('tex','uv','alpha','color','blend','flipX','flipY'):
                    self.assertEqual(a[field],b[field])
                self.assertNotIn(a,kept['frames'][fi])
        self.assertEqual(sum(map(len,doc['frames'])),sum(map(len,kept['frames']))+sum(map(len,flashes['frames'])))

    def test_prepare_partition_keeps_source_coverage_clock_and_no_double_offset(self):
        key='GL_2024/ability/1'
        native={'kit':{'name':'Fixture','entries':[{'kind':'ABILITY','status':'ready','name':'Flash','sourceKey':key}]},
                'profiles':{key:{'snapshot':{'root':key}}}}
        timeline={'spawns':[spawn(20),spawn(60)],'sounds':[{'frame':62,'cueId':29}],
                  'issues':[],'targetType':'Single','visualCoverage':{'complete':True,'omitted':[]}}
        original=deepcopy(timeline)
        source={'pixelsPerUnit':2.4,'textures':['solid'],'frames':[[],[sprite()],[]]}
        captured=[]
        def convert(doc,folder,name,**kwargs):
            captured.append(deepcopy(doc));folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
            spec={'textureFile':'tex.bgra','model':{'parts':[{'name':'root'}]},
                  'animations':[{'isSetup':True,'parts':{'root':{}}}]}
            (folder/'spec.json').write_text(json.dumps(spec));(folder/'tex.bgra').write_bytes(b'fixture')
            return spec
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with (patch.object(prepare,'ROOT',root),patch.object(prepare,'WORK',root/'work'),
                  patch.object(prepare,'ASSETS',root/'assets'),
                  patch.object(prepare.presentation,'BUNDLES',root/'manifests'),
                  patch.object(prepare,'native_kit',return_value=native),
                  patch.object(prepare,'timeline',side_effect=lambda *a,**k:deepcopy(timeline)),
                  patch.object(prepare,'universal_unit_geometry',return_value={}),
                  patch.object(prepare.host_coordinates,'adapt_timeline',side_effect=lambda data,*a,**k:data),
                  patch.object(prepare,'source_action_timing',return_value=(120,'fixture source clock')),
                  patch.object(prepare,'bake_source',return_value=(deepcopy(source),{'issues':[]})),
                  patch.object(prepare.to_ss6,'load_texture',side_effect=self.texture),
                  patch.object(prepare.to_ss6,'complete_export',return_value=False),
                  patch.object(prepare.to_ss6,'convert',side_effect=convert),
                  patch.object(prepare,'AudioLibrary') as audio):
                audio.return_value.selection.return_value={'omitted':{}}
                report=prepare.prepare(['1'],[key],detect_scene=True,universal=True,make_previews=False)
            entry=report['forms']['1']['moves'][key]
        self.assertEqual(original,timeline)
        self.assertEqual(original['spawns'],entry['spawns'])
        self.assertEqual(original['sounds'],entry['sounds'])
        self.assertTrue(entry['visualCoverage']['complete'])
        self.assertEqual([],entry['visualCoverage']['omitted'])
        self.assertEqual('battlefield',entry['backgroundDetection']['kind'])
        self.assertEqual(1,len(entry['visuals']))
        visual=entry['visuals'][0]
        self.assertEqual(('screen',20),(visual['anchor'],visual['frame']))
        self.assertEqual('camera_plane',visual['placement']['mode'])
        self.assertEqual([0,0],visual['placement']['sourceOffset'])
        self.assertNotIn('sourceCoordinates',visual)
        self.assertEqual(1,len(captured))
        self.assertEqual([21,61],[visual['frame']+i-2 for i,f in enumerate(captured[0]['frames']) if f])
        for frame in captured[0]['frames']:
            for part in frame:
                self.assertEqual([0.,0.],part['pos'])
                self.assertEqual([96.,96.],part['scale'])


if __name__=='__main__':unittest.main()
