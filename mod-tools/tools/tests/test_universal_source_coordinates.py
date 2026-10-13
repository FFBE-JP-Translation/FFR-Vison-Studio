"""Universal preparation translates source offsets while keeping the source clock."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ffbe_effects import prepare_vision as prepare
from ffbe_effects.host_coordinates import adapt_timeline, parse_unit_geometry
from ffbe_effects.source_placement import normalize_effect_placement, normalize_skill_placement


class UniversalCoordinates(unittest.TestCase):
    def data(self, anchor, source_frame=28, group_frame=40, offset=(0,0), modes=(5,5)):
        effect=normalize_effect_placement(f'{source_frame}:1:0:0:{modes[0]}:{modes[1]}:{offset[0]}:{offset[1]}')
        return {'spawns':[{'file':'a.bmb','source':'GL_2024/ability/1','groupId':'9',
            'frame':source_frame+group_frame,'sourceGroupFrame':group_frame,
            'sourceSkillPlacement':normalize_skill_placement(f'1:{anchor}:0'),
            'sourceEffectPlacement':effect,'anchor':{1:'each_target',3:'caster',4:'screen'}[anchor],
            'layer':1,'scale':1,'rotation':[0,0,0],'x':offset[0],'y':offset[1]}],
            'sounds':[{'frame':68,'cueId':100}], 'issues':[], 'sourcePlacement':{'groups':[]}}

    def test_delayed_child_wait_is_baked_from_dispatch_and_raw_fields_and_audio_remain(self):
        data=self.data(3,offset=(-100,40));original=deepcopy(data)
        geometry=parse_unit_geometry({'TouchRect':'114:139:49:105','MoveOffset':'120:0,180:0','MoveSpeed':'5'},[300,280])
        adapt_timeline(data,geometry)
        self.assertEqual(original['sounds'],data['sounds'])
        for key in ('frame','x','y','sourceSkillPlacement','sourceEffectPlacement'):
            self.assertEqual(original['spawns'][0][key],data['spawns'][0][key])
        doc={'textures':['unused.png'],'frames':[[{'tex':0,'pos':[0,0],'scale':[1,1],'rot':0}]]}
        first,result=prepare.compose(data['spawns'],{'a.bmb':doc})
        self.assertEqual(40,first)
        visible=[i for i,frame in enumerate(result['frames']) if frame]
        self.assertEqual([30],visible)  # 28 authored wait +two hidden SS6 leadframes.
        self.assertAlmostEqual(-267.6,result['frames'][30][0]['pos'][0])
        self.assertAlmostEqual(116.4,result['frames'][30][0]['pos'][1])
        self.assertEqual('actor_root_snapshot',data['spawns'][0]['hostCoordinates']['binding'])

    def test_source_screen_minimum_and_center_modes_fix_offset_relative_to_source_rectangle(self):
        geometry=parse_unit_geometry({'TouchRect':'','MoveOffset':'','MoveSpeed':'0'},[64,64])
        data=self.data(4,offset=(0,150),modes=(5,4))
        adapt_timeline(data,geometry,reference_stage=[320,320])
        self.assertEqual([160,150],data['spawns'][0]['hostCoordinates']['sourcePosition'])
        self.assertEqual([0,-10],data['spawns'][0]['hostCoordinates']['sourceOffset'])
        self.assertEqual(150,data['spawns'][0]['y'])

    def test_target_proxy_and_jitter_approximation_are_reported(self):
        geometry=parse_unit_geometry({'TouchRect':'','MoveOffset':'','MoveSpeed':'0'},[64,64])
        first=self.data(1,modes=(2,2));second=deepcopy(first)
        adapt_timeline(first,geometry,seed=17);adapt_timeline(second,geometry,seed=17)
        self.assertEqual(first,second)
        self.assertTrue(any('64x128' in issue for issue in first['issues']))
        self.assertTrue(any('native RNG' in issue for issue in first['issues']))
        self.assertEqual('target',first['spawns'][0]['hostCoordinates']['owner'])

    def test_exact_client_snapshot_raw_master_schedule_is_used_when_normalized_absent(self):
        data={'_master':{'effect_frames':'0:9:1:3:0&10:8:2:4:0@20:7:1:1:0'}}
        self.assertEqual([],prepare.snapshot_effect_frames(data))
        self.assertEqual([0,10,20],prepare.snapshot_effect_frames(data,source_matched=True))
        self.assertIsNone(prepare.snapshot_effect_frames({},source_matched=True))
        self.assertEqual([],prepare.snapshot_effect_frames({'_master':{'effect_frames':''}},source_matched=True))


if __name__=='__main__':unittest.main()
