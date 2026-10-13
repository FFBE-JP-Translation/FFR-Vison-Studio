"""Random ailment choices retain selection, recipient and native row contracts."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter, SourceRecord, commands
from ability_converter.adapters import AILMENTS
from ability_converter.compiler import TableWriter


def source(chances=None, maximum=1, code=146, **data):
    chances=[100]*8 if chances is None else chances
    params=chances+[1,maximum] if code==34 else [chances]+[0]*8+[maximum]
    return SourceRecord('TEST','ability','random',{'name':'Random ailment',
        'effects_raw':[[2,1,code,params]],'attack_frames':[[24]],'attack_damage':[[100]],
        'mp_cost':12,**data})


def outcomes(spec, probability=Fraction(1)):
    if choices:=spec.get('randomChoices'):
        return [outcome for child in choices for outcome in outcomes(child,probability/len(choices))]
    def statuses(node):
        return [s for child in node['children'] for s in statuses(child)] if node.get('children') else [node['set']['statusCondition']]
    return [(probability,statuses(spec))]


class RandomAilmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()

    def convert(self,*args,**kwargs):
        result=self.c.convert(source(*args,**kwargs))
        self.assertTrue(result['validation']['tableCompatible'],result['issues'])
        return result

    def test_one_choice_preserves_every_outcome_and_equal_branches(self):
        for count in (1,2,3,4,5,6,8):
            with self.subTest(count=count):
                result=self.convert([100]*count+[0]*(8-count))
                root=result['native']['effects'][0]
                observed=outcomes(root)
                self.assertEqual(len(observed),count)
                self.assertTrue(all(p==Fraction(1,count) for p,_ in observed))
                self.assertEqual([s for _,ss in observed for s in ss],
                    [s for name in AILMENTS[:count] for s in (['AttackDown','IntelligenceDown'] if name=='Disease' else [name])])
                self.assertEqual(len(result['native']['effects']),1)

    def test_seven_way_choice_is_held_without_partial_export(self):
        r=self.c.convert(source([100]*7+[0]))
        self.assertFalse(r['validation']['tableCompatible'])
        self.assertIn('unbiased native selection tree',' '.join(r['issues']))
        self.assertFalse(r['components'][0]['effects'])

    def test_all_selected_has_no_random_branch(self):
        r=self.convert(maximum=8);root=r['native']['effects'][0]
        self.assertEqual(root['set']['EffectType'],'AddEffect')
        self.assertEqual(len(outcomes(root)[0][1]),9)
        def check(node):
            self.assertNotIn('randomChoices',node)
            for child in node.get('children',[]):check(child)
        check(root)
        self.assertIn('Attempts these ailments on all enemies:',TableWriter.description(r))

    def test_disease_is_one_paired_outcome(self):
        r=self.convert([100,0,0,0,0,0,100,0])
        self.assertEqual(outcomes(r['native']['effects'][0]),[(Fraction(1,2),['Poison']),
            (Fraction(1,2),['AttackDown','IntelligenceDown'])])
        self.assertIn('one randomly selected ailment',TableWriter.description(r))
        self.assertIn('Enfeebled (ATK and MAG down)',TableWriter.description(r))

    def test_chance_order_and_without_replacement_stay_held(self):
        for chances,count,issue in (([50]*8,1,'selection-versus-chance'),([100]*8,3,'without replacement'),
                                    ([100]*8,9,'outside its decoded range')):
            r=self.c.convert(source(chances,count))
            self.assertFalse(r['validation']['tableCompatible'])
            self.assertIn(issue,' '.join(r['issues']))
            self.assertFalse(r['components'][0]['effects'])

    def test_opcode_146_uses_its_nested_vector_and_controls(self):
        a=self.convert(code=34);b=self.convert(code=146)
        self.assertIn('orderedAilments',a['native']['effects'][0])
        self.assertIn('randomChoices',b['native']['effects'][0])
        for code in (34,146):
            for control in (True,0.5,2):
                record=source(code=code);record.data['effects_raw'][0][3][8 if code==34 else 1]=control
                self.assertFalse(self.c.convert(record)['validation']['tableCompatible'])

    def test_zero_count_and_empty_pool_remain_noops(self):
        for code in (34,146):
            for record in (source(maximum=0,code=code),source([0]*8,code=code)):
                result=self.c.convert(record)
                self.assertEqual(result['status'],'noop')
                self.assertEqual(result['components'][0]['raw'],record.data['effects_raw'][0])
                self.assertFalse(result['components'][0]['effects'])

    def test_malformed_vectors_cannot_be_silently_truncated(self):
        for value in ([100]*7,[100]*9,[100]*7+[True],[100]*7+[float('nan')]):
            result=self.c.convert(source(value,code=146))
            self.assertFalse(result['validation']['tableCompatible'])

    def test_all_choice_nodes_keep_the_original_recipient(self):
        record=source();record.data['effects_raw'][0][:2]=[0,3]
        result=self.c.convert(record);self.assertTrue(result['validation']['tableCompatible'],result['issues'])
        def check(node):
            self.assertEqual(node['target']['shape'],'Self')
            self.assertEqual(node['target']['relation'],'Friendlies')
            for child in node.get('randomChoices',node.get('children',[])):check(child)
        check(result['native']['effects'][0])

    def test_serialization_resolves_choices_and_bundles_to_private_rows(self):
        result=self.convert();writer=TableWriter(self.c.native);sid=writer.add(result)
        patch=writer.patch(ROOT/'build/abilities/random-fixture')
        effects=next(t for t in patch['tables'] if t['asset'].endswith('DT_SkillEffectData'))['add']
        rows={r['set']['ID']:r['set'] for r in effects}
        self.assertEqual(len([r for r in rows.values() if r['EffectType']=='AddRandEffect']),3)
        self.assertEqual(len([r for r in rows.values() if r['EffectType']=='AddEffect']),1)
        for row in rows.values():
            if row['EffectType'] in ('AddRandEffect','AddEffect'):
                active=[x for x in row['ParamList'][1:] if x!=-1]
                self.assertTrue(all(x in rows for x in active))
                self.assertLessEqual(len(active),5 if row['EffectType']=='AddRandEffect' else 4)
        # Export twice with retained IDs; no source/cooked stock row is overwritten.
        other=TableWriter(self.c.native,deepcopy(writer.ledger));self.assertEqual(other.add(result),sid)
        self.assertEqual(other.patch(ROOT/'build/abilities/random-fixture'),patch)

    def test_mutated_choice_contract_is_rejected_before_allocating_ids(self):
        base=self.convert()
        for field,value in (('ParamList',[1]+[-1]*14),('proceedTiming','BeginTurn'),('effectEndActionNum',1),
                            ('addProbability',50),('statusCondition','Poison'),('isExecutingReaction',True)):
            result=deepcopy(base);result['native']['effects'][0]['set'][field]=value
            writer=TableWriter(self.c.native);original=deepcopy(writer.ledger)
            with self.assertRaises(ValueError):writer.add(result)
            self.assertEqual(writer.ledger,original)
            self.assertFalse(writer.tables)
        result=deepcopy(base)
        result['native']['effects'][0]['randomChoices'][0]['randomChoices'].pop()
        with self.assertRaisesRegex(ValueError,'equally sized'):TableWriter(self.c.native).add(result)
        result=deepcopy(base)
        result['native']['effects'][0]['randomChoices'][0]['target']['shape']='Self'
        with self.assertRaisesRegex(ValueError,'recipient'):TableWriter(self.c.native).add(result)
        for spec_key in ('randomChoices','children'):
            result=deepcopy(base) if spec_key=='randomChoices' else self.convert(maximum=8)
            del result['native']['effects'][0][spec_key]
            with self.assertRaises(ValueError):TableWriter(self.c.native).add(result)

    def test_command_snapshot_rebuild_preserves_tree_and_single_application(self):
        p=commands.profile(source());self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(p['timeline']['hitFrames'],[24])
        rebuilt=commands.from_snapshot(json.loads(json.dumps(p['snapshot'])))
        self.assertTrue(rebuilt['supported'],rebuilt['issues'])
        self.assertEqual(p['conversion']['native'],rebuilt['conversion']['native'])


if __name__=='__main__':unittest.main()
