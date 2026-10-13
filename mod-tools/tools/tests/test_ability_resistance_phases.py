"""Regression coverage for damage followed by native elemental resistance."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import commands,SourceRecord
from ability_converter.resistance_phases import evidence,CHANGE


def source(effects=None):
    return SourceRecord('CUSTOM','magic','20010',{'name':'Fire','mp_cost':3,'element_inflict':['Fire'],
        'effects_raw':effects or [[1,1,15,[0,0,0,0,0,120,0]],
            [1,1,33,[-100,0,0,0,0,0,0,0,1,5]],[0,3,125,[400,400]]],
        'attack_frames':[[80]],'attack_damage':[[100]],'move_type':0})


class ResistancePhaseTests(unittest.TestCase):
    def test_fire_import_and_portable_snapshot_keep_independent_recipients(self):
        p=commands.profile(source())
        self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(p['timeline']['hitFrames'],[80])
        self.assertEqual([e['effectType'] for e in p['timeline']['effectPhases']],['AddElementResistance','ParameterVariation'])
        self.assertEqual(p['timeline']['effectPhases'][0]['evidence']['durationClock'],'native_shared_battle_turn')
        self.assertIn(CHANGE,p['warnings'])
        rebuilt=commands.from_snapshot(p['snapshot'])
        self.assertEqual(rebuilt['timeline'],p['timeline'])
        tables={}
        def table(name):return tables.setdefault(name,{'add':[],'set':[]})
        native=commands.converter().native
        def row_by(table_,field,id_):return native.effect_names[id_],native.effects[id_]
        row=commands.materialize(p,890010,'FireTest',table,row_by)
        self.assertEqual([(e['TargetType'],e['targetRelation'],e['activeSkillAddTiming']) for e in row['effectBundleList']],
            [('SkillTarget','Enemies','AfterDamageCalculation'),('Self','Friendlies','AfterDamageCalculation')])
        self.assertEqual([e['set']['ParamList'][:2] for e in tables['Skill/DT_SkillEffectData']['add']],[[1,1],[4,4]])

    def test_all_native_element_categories_and_lifetimes(self):
        native=commands.converter().native
        for element in range(1,9):
            for category in range(1,5):
                for turns in (1,5,native.general['effectMaxLifeTime']):
                    with self.subTest(element=element,category=category,turns=turns):
                        effect=native.effect(1022,[element,category],turns=turns)
                        effect['activeTiming']='AfterDamageCalculation'
                        self.assertIsNotNone(evidence(native,effect,'Decrease'))

    def test_before_damage_and_recovery_do_not_borrow_this_contract(self):
        original=source().data['effects_raw']
        before=commands.profile(source([original[1],original[0]]))
        self.assertFalse(before['supported'])
        self.assertIn('BeforeDamageCalculation',' '.join(before['issues']))
        native=commands.converter().native
        effect=native.effect(1022,[1,1],turns=5)
        effect['activeTiming']='AfterDamageCalculation'
        self.assertIsNone(evidence(native,effect,'Increase'))

    def test_independent_group_resistance_remains_separate_from_damage_target(self):
        original=source().data['effects_raw']
        for target in (1,2):
            with self.subTest(target=target):
                p=commands.profile(source([original[0],[2,target,33,[-100,0,0,0,0,0,0,0,1,5]]]))
                self.assertTrue(p['supported'],p['issues'])
                effect=p['conversion']['native']['effects'][0]
                self.assertEqual(effect['target']['shape'],'Group')

    def test_tampered_effects_are_rejected(self):
        native=commands.converter().native
        base=native.effect(1022,[1,1],turns=5)
        base['activeTiming']='AfterDamageCalculation'
        for field,value in (('applyTiming','AddEffect'),('proceedTiming','ActionBegin'),
                ('effectEndActionNum',0),('addProbability',12.5),('ParamList',[1,6]+[-1]*13),
                ('ParamList',[1,1,999]+[-1]*12)):
            with self.subTest(field=field,value=value):
                effect=deepcopy(base);effect['set'][field]=value
                with self.assertRaises(ValueError):evidence(native,effect,'Decrease')

    def test_native_template_and_timing_drift_are_rejected(self):
        native=deepcopy(commands.converter().native)
        effect=native.effect(1022,[1,1],turns=5);effect['activeTiming']='AfterDamageCalculation'
        native.effects[1022]['ParamList'][1]=3
        with self.assertRaisesRegex(ValueError,'template changed'):evidence(native,effect,'Decrease')
        native=deepcopy(commands.converter().native)
        native.inventory['enums']['eSkillTiming']['BeginTurn']=99
        with self.assertRaisesRegex(ValueError,'timing changed'):evidence(native,effect,'Decrease')


if __name__=='__main__':unittest.main()
