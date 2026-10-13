"""Native buff/debuff replacements retain their scope and removal protection."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands
from ability_converter.compiler import TableWriter


def source(selection=0,control=0,shape=2,side=1,**data):
    return SourceRecord('TEST','magic','59',{'name':'Dispel',
        'effects_raw':[[shape,side,59,[selection]+([] if control is None else [control])]],
        'attack_frames':[[24]],'attack_damage':[[100]],'mp_cost':12,**data})


class DispelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()

    def convert(self,**kw):
        r=self.c.convert(source(**kw));self.assertTrue(r['validation']['tableCompatible'],r['issues'])
        self.assertEqual(r['status'],'replaced');return r

    def test_combined_removal_uses_two_operations_in_source_order(self):
        r=self.convert();effects=r['native']['effects']
        self.assertEqual([e['template'] for e in effects],[1181,20012])
        self.assertEqual([e['removal']['mode'] for e in effects],['buffs','debuffs'])
        self.assertEqual(effects[0]['set']['ParamList'],[0,1,0,0,0,0,0,0,0,1]+[-1]*5)
        self.assertEqual(effects[1]['set']['ParamList'],[0]*10+[1]+[-1]*4)

    def test_buff_and_debuff_selectors_never_remove_the_opposite_category(self):
        for selection,mode,template in ((1,'buffs',1181),(2,'debuffs',20012)):
            effects=self.convert(selection=selection)['native']['effects']
            self.assertEqual(len(effects),1);self.assertEqual(effects[0]['template'],template)
            self.assertEqual(effects[0]['removal']['mode'],mode)

    def test_removal_lists_preserve_ailments_reraise_and_unlabelled_effects(self):
        effects=self.convert()['native']['effects']
        buffs,debuffs=[set(e['removal']['statuses']) for e in effects]
        self.assertEqual(len(buffs),26)
        self.assertEqual(debuffs,{'Slow','AttackDown','DeffenceDown','IntelligenceDown','MindDown','BreakDmgDown','BreakDmgTakenUp'})
        self.assertFalse(buffs & debuffs)
        self.assertFalse((buffs|debuffs)&{'None','Poison','Blind','Stoned','Reraise','Charme'})
        self.assertTrue(all(e['removal']['preservesUnremovable'] for e in effects))

    def test_none_and_numeric_zero_normalize_without_changing_raw_source(self):
        a=self.convert(selection='none');b=self.convert(selection=0)
        self.assertEqual(a['native'],b['native'])
        self.assertEqual(a['components'][0]['raw'][-1][0],'none')
        self.assertEqual(a['components'][0]['semantic']['sourceSelection'],'none')

    def test_optional_neutral_control_is_equivalent_and_unknown_controls_hold(self):
        self.assertEqual(self.convert(control=None)['native'],self.convert(control=0)['native'])
        for control in (1,-1,True,.5,'0'):
            r=self.c.convert(source(control=control));self.assertFalse(r['validation']['tableCompatible'])
            self.assertFalse(r['components'][0]['effects'])

    def test_bad_selectors_and_parameter_shapes_hold(self):
        for selection in (True,False,-1,3,.5,'1',None,[]):
            r=self.c.convert(source(selection=selection));self.assertFalse(r['validation']['tableCompatible'])
        for params in ([],[0,0,0]):
            record=source();record.data['effects_raw'][0][3]=params
            self.assertFalse(self.c.convert(record)['validation']['tableCompatible'])

    def test_recipient_filters_remain_on_the_root_selection(self):
        for shape,side in ((0,3),(1,2),(2,1),(2,5)):
            r=self.convert(shape=shape,side=side);effects=r['native']['effects']
            self.assertEqual(effects[0]['target'],effects[1]['target'])
            w=TableWriter(self.c.native);w.add(r)
            row=w.tables['Skill/DT_SkillData']['add'][0]['set']
            self.assertEqual(row['isTargetIgnoreSelf'],side==5)
            self.assertEqual(row['effectBundleList'][0]['targetRelation'],'Enemies' if side==1 else 'Friendlies')

    def test_snapshot_keeps_one_support_event_and_the_replacement_warning(self):
        p=commands.profile(source());self.assertTrue(p['supported'],p['issues'])
        restored=commands.from_snapshot(p['snapshot'])
        self.assertEqual(restored['timeline']['hitFrames'],[24])
        self.assertEqual(len(restored['conversion']['native']['effects']),2)
        self.assertIn('native status allowlists',' '.join(restored['warnings']))
        self.assertIn('Removes dispellable buffs',restored['description'])
        self.assertIn('Slow, ATK/DEF/MAG/SPR penalties',restored['description'])

    def test_missing_or_tampered_binding_is_rejected_before_allocation(self):
        for mutate in (lambda e:e.pop('removal'),lambda e:e['removal'].__setitem__('preservesUnremovable',False),
                       lambda e:e['set']['ParamList'].__setitem__(0,1),lambda e:e['set'].__setitem__('addProbability',50),
                       lambda e:e['removal']['statuses'].append('Poison')):
            r=self.convert();mutate(r['native']['effects'][0]);w=TableWriter(self.c.native)
            with self.assertRaises(ValueError):w.add(r)
            self.assertEqual(w.tables,{});self.assertTrue(all(not x for x in w.ledger.values()))

    def test_native_allowlist_category_drift_is_rejected(self):
        n=deepcopy(self.c.native)
        next(s for s in n.inventory['statuses'] if s['statusCondition']=='Poison')['isDispelToOut']=True
        r=Converter(native=n).convert(source())
        self.assertFalse(r['validation']['tableCompatible']);self.assertIn('category',' '.join(r['issues']))

    def test_damaging_dispel_keeps_damage_and_uses_native_effect_phase(self):
        record=source();record.data['effects_raw'].insert(0,[2,1,1,[0,0,0,0,0,0,500]])
        p=commands.profile(record);self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(p['conversion']['native']['set']['DamageType'],'Physic')
        self.assertEqual([e['activeTiming'] for e in p['conversion']['native']['effects']],['AfterDamageCalculation']*2)
        self.assertEqual(len(p['timeline']['effectPhases']),2)


if __name__=='__main__':unittest.main()
