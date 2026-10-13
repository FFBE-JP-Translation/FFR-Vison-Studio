"""Scene policy must distinguish background replacement from ordinary effects."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from PIL import Image

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/ffbe_effects'))
import scene


def plate(alpha=1.,blend='mix',size=510,rotation=0):
    return {'tex':0,'uv':[0,0,32,32],'pos':[0,0], 'scale':[size*2.4/32]*2,
            'rot':rotation,'alpha':alpha,'blend':blend}


def spawn(anchor='screen',layer=2):
    return {'file':'arbitrary.bmb','groupId':'42','anchor':anchor,'layer':layer,
            'frame':0,'scale':1.,'x':0,'y':0,'rotation':[0,0,0]}


class SourceScene(unittest.TestCase):
    def classify(self,sprites,source=None,texture_alpha=255):
        doc={'pixelsPerUnit':2.4,'textures':['neutral.png'],'frames':sprites}
        return scene.classify([source or spawn()],{'arbitrary.bmb':doc},
                              lambda _:Image.new('RGBA',(32,32),(40,50,100,texture_alpha)))

    def test_sustained_opaque_rear_screen_plate_is_detected_without_names(self):
        result=self.classify([[plate()]]*90)
        self.assertEqual('replacement_background',result['kind'])
        self.assertEqual(90,result['evidence'][0]['longestOpaqueRun'])

    def test_overlay_flash_transparent_ring_and_caster_never_create_background(self):
        for frames,s,alpha in [([[plate()]]*90,spawn('caster'),255),
                               ([[plate()]]*90,spawn(layer=1),255),
                               ([[plate(blend='add')]]*90,spawn(),255),
                               ([[plate()]]*90,spawn(),80),
                               ([[plate(size=64)]]*90,spawn(),255),
                               ([[plate()]]*6+[[]]*84,spawn(),255),
                               (([[plate()]]+[[]])*45,spawn(),255)]:
            with self.subTest(source=s,alpha=alpha):
                self.assertNotEqual('replacement_background',self.classify(frames,s,alpha)['kind'])

    def test_rotated_plate_must_cover_corners_not_just_axis_aligned_bounds(self):
        self.assertNotEqual('replacement_background',self.classify([[plate(size=350,rotation=45)]]*90)['kind'])

    def test_late_opaque_speedline_is_an_overlay_not_a_whole_action_background(self):
        source={**spawn(),'frame':195}
        self.assertEqual('screen_overlay',self.classify([[plate()]]*180,source)['kind'])

    def test_casting_background_does_not_replace_the_whole_action_battlefield(self):
        source={**spawn(),'phase':'cast'}
        result=self.classify([[plate()]]*180,source)
        self.assertEqual('screen_overlay',result['kind'])
        self.assertEqual([],result['evidence'])

    def test_cover_fits_all_corners_and_leaves_small_particles_and_source_unchanged(self):
        doc={'pixelsPerUnit':2.4,'textures':['plate.png'],
             'frames':[[plate(),plate(size=20,blend='add')]]*90}
        original=deepcopy(doc)
        load=lambda _:Image.new('RGBA',(32,32),(10,20,30,255))
        detected=scene.classify([spawn()],{'arbitrary.bmb':doc},load)
        bounds=[-550,-280,300,430]
        result,audit=scene.cover_background(doc,detected,[spawn()],bounds,load)
        self.assertEqual(doc,original)
        self.assertEqual(90,audit['spriteFrames'])
        for frame in result['frames']:
            self.assertLess(scene.cover_factor(frame[0],bounds,2.4),1)
            self.assertEqual(original['frames'][0][1],frame[1])
            self.assertEqual(1.,frame[0]['alpha'])

    def test_real_rain_fina_classification_and_sora_screenless_source(self):
        import to_ss6
        base=ROOT/'build/rain-fina-motion/prepared/decoded'
        if not base.is_dir():
            self.skipTest('Local FFBE source fixture not distributed')
        docs={}
        for folder in base.iterdir():
            if (folder/'audit.json').is_file():
                audit=json.loads((folder/'audit.json').read_text())
                if audit.get('decoder')==13:
                    docs[audit['file']]=json.loads((folder/'doc.json').read_text())
        rf=json.loads((ROOT/'data/ffbe/presentation/100032707.json').read_text())
        entry=rf['moves']['GL_2024/lb/100032707/level/40']
        result=scene.classify(entry['spawns'],docs,to_ss6.load_texture)
        self.assertEqual('replacement_background',result['kind'])
        self.assertEqual(['8008450'],[e['groupId'] for e in result['evidence']])
        sora=json.loads((ROOT/'data/ffbe/presentation/340000107.json').read_text())
        lb=next(v for k,v in sora['moves'].items() if '/lb/' in k)
        # Include the actual late screen layers omitted by the older exporter;
        # testing only caster slashes would miss the speedline false positive.
        omitted=[o['spawn'] for o in lb.get('visualCoverage',{}).get('omitted',[]) if 'spawn' in o]
        sources=lb['spawns']+omitted
        rear={s['file'] for s in sources if s['anchor']=='screen' and s['layer']==2}
        source_docs={}
        for folder in (ROOT/'build/ffbe-effects-offline/decoded').glob('*'):
            if (folder/'audit.json').is_file():
                info=json.loads((folder/'audit.json').read_text())
                if info['file'] in rear:
                    source_docs[info['file']]=json.loads((folder/'doc.json').read_text())
        if rear and rear <= source_docs.keys():
            result=scene.classify(sources,source_docs,to_ss6.load_texture,action_frames=339)
            self.assertEqual('screen_overlay',result['kind'])
            self.assertEqual([],result['evidence'])
        elif rear:
            self.skipTest('Local Sora source screen fixture not distributed')
        else:
            self.assertEqual('battlefield',scene.classify(sources,{},to_ss6.load_texture)['kind'])


if __name__=='__main__':
    unittest.main()
