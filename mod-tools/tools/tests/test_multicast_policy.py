import json
from pathlib import Path
import sys
import unittest
from copy import deepcopy

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'),str(ROOT/'tools/devui')]
from ability_converter import commands,multicast,SourceRecord


class MulticastPolicyTests(unittest.TestCase):
    def profile(self,raw,kind='ability'):
        return commands.profile(SourceRecord('GL_2024',kind,'1',{'name':'Fixture','effects_raw':raw,
            'attack_frames':[[12]],'attack_damage':[[100]],'move_type':4}),reviewed=True)

    def test_all_multicast_families_are_omitted(self):
        for code in (44,45,97,98,168,1006):
            p=self.profile([[0,3,code,[0,0,0,0,0,0,0]]])
            self.assertFalse(p['supported']);self.assertEqual(p['disabledBy'],'multicast')
        for code in (52,53,102):
            p=self.profile([[0,3,code,[0,0,0,0]]],'passive')
            self.assertFalse(p['supported']);self.assertEqual(p['disabledBy'],'multicast')

    def test_mixed_abilities_keep_damage_and_passives_keep_stats(self):
        p=self.profile([[1,1,1,[0,0,0,0,0,0,500,0]],[0,3,45,['none']]])
        self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(p['set']['DamageType'],'Physic')
        self.assertFalse(p['conversion']['native']['effects'])
        p=self.profile([[0,3,1,[20,0,0,0,0,0]],[0,3,52,[0]]],'passive')
        self.assertTrue(p['supported'],p['issues'])
        self.assertTrue(all(e['set']['ParamList'][1] != 9 for e in p['conversion']['native']['effects']))

    def test_def_scaling_variant_is_not_classified_as_multicast(self):
        self.assertFalse(multicast.component('active',[1,1,102,[100,0,500]]))
        self.assertTrue(multicast.component('active',[0,3,102,[2,1,3,[123]]]))

    def test_saved_dualcast_is_archived_without_reordering_other_grants(self):
        p=self.profile([[0,3,45,['none']]])
        recipe={'mechanics':'converted','effectPolicy':'ffbe-ffr-reviewed/203.1','conversionSource':p['snapshot'],
                'ffbe':{'source':'GL_2024/ability/1'}}
        u={'skills':{'485000':recipe},'awakening':[[['BaseParameter',5,10],['ActiveSkill',485000],['PassiveSkill',100]],[],[],[]],
           'nativeImports':['GL_2024/ability/1'],'ffbeMap':{'skills':{'1':485000}}}
        multicast.remove_disabled_grants(u)
        self.assertEqual(u['awakening'][0],[['BaseParameter',5,10],['PassiveSkill',100]])
        self.assertFalse(u['skills']);self.assertFalse(u['nativeImports']);self.assertFalse(u['ffbeMap']['skills'])
        self.assertEqual(u['conversionArchive'][0]['entry'],recipe)
        saved=deepcopy(u);multicast.remove_disabled_grants(u);self.assertEqual(u,saved)

    def test_approach_keeps_clearance_and_places_attacker_in_front(self):
        p=self.profile([[1,1,1,[0,0,0,0,0,0,500,0]]])
        plan=commands.schedule(p,485000,2.,'attack_A')
        move=next(e['set'] for e in plan['events'] if e['set']['EventType']=='UnitMoveToTarget')
        self.assertEqual(move['Unit_MoveToTarget_AddLocation'],{'x':-80.,'y':200.,'z':0.})
        self.assertFalse(move['Unit_MoveToTarget_IsDisableOffset'])
        self.assertTrue(move['Unit_MoveToTarget_IsVisionUnit'])
        self.assertTrue(any(e['set'].get('Unit_MoveToDefaultLocation_IsVision') for e in plan['events']))


if __name__ == '__main__': unittest.main()
