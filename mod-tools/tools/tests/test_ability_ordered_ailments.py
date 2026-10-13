"""Independent probability checks and native row-graph execution for active 34."""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
from itertools import product
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter, commands
from ability_converter.compiler import TableWriter
from ability_converter.ordered_ailments import distribution, weights, RESOLUTION
from test_ability_random import source


class OrderedAilmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()

    def result(self,chances=None,maximum=1):
        result=self.c.convert(source(chances,maximum,code=34))
        self.assertTrue(result['validation']['tableCompatible'],result['issues'])
        return result

    def test_source_poison_first_order_stops_on_guaranteed_success(self):
        for maximum in range(1,9):
            result=self.result(maximum=maximum)
            plan=result['native']['effects'][0]['orderedAilments']
            self.assertEqual(plan['outcomes'],[{'mask':(1<<maximum)-1,'tickets':RESOLUTION}])
            self.assertEqual(result['status'],'replaced')
            self.assertIn('resistance',TableWriter.description(result))

    def test_first_success_probabilities_include_failure(self):
        actual=dict(distribution((50,25,0,0,0,0,0,0),1))
        self.assertEqual(actual,{0:Fraction(3,8),1:Fraction(1,2),2:Fraction(1,8)})

    def test_independent_bernoulli_oracle_all_caps(self):
        chances=(13,27,41,53,67,79,83,97)
        for cap in range(1,9):
            expected=Counter()
            for bits in product((0,1),repeat=8):
                p=Fraction(1);selected=[]
                for i,(bit,chance) in enumerate(zip(bits,chances)):
                    p*=Fraction(chance if bit else 100-chance,100)
                    if bit and len(selected)<cap:selected.append(i)
                expected[sum(1<<i for i in selected)]+=p
            self.assertEqual(dict(distribution(chances,cap)),dict(expected))
            rounded=dict(weights(chances,cap))
            self.assertEqual(sum(rounded.values()),RESOLUTION)
            for mask,p in expected.items():
                self.assertLess(abs(Fraction(rounded[mask],RESOLUTION)-p),Fraction(1,RESOLUTION))
                self.assertLessEqual(mask.bit_count(),cap)

    def test_uncapped_chances_have_correct_marginals(self):
        chances=(20,40,60,80,10,30,50,70)
        values=distribution(chances,8)
        for i,chance in enumerate(chances):
            self.assertEqual(sum(p for mask,p in values if mask & 1<<i),Fraction(chance,100))

    def test_small_probabilities_are_retained_with_explicit_rounding(self):
        result=self.result([0.0001]+[0]*7)
        plan=result['native']['effects'][0]['orderedAilments']
        self.assertEqual(plan['outcomes'],[{'mask':0,'tickets':RESOLUTION},{'mask':1,'tickets':0}])
        self.assertGreater(plan['maximumOutcomeErrorPercent'],0)
        self.assertFalse(result['native']['effects'][0]['ailmentEffects'])

    def compiled(self,result):
        writer=TableWriter(self.c.native);writer.add(result)
        rows={e['set']['ID']:e['set'] for e in writer.tables['Skill/DT_SkillEffectData']['add']}
        skill=writer.tables['Skill/DT_SkillData']['add'][0]['set']
        return writer,rows,skill['effectBundleList'][0]['effectId']

    def test_compiled_native_choices_recover_every_quantized_outcome(self):
        for chances,cap in (([30]*7+[100],1),([40]*8,3),([50]*8,4),([100]*8,8),([0.0001]+[0]*7,1)):
            with self.subTest(chances=chances,cap=cap):
                result=self.result(chances,cap);writer,rows,root=self.compiled(result)
                self.assertEqual(rows[root]['EffectType'],'AddRandEffect')
                # Evaluate the emitted native graph, independently of the
                # unresolved plan/tree builder. Bundles convolve child effects.
                cache={}
                def walk(eid,depth=0):
                    self.assertLessEqual(depth,11)
                    if eid in cache:return cache[eid]
                    row=rows[eid];children=[i for i in row['ParamList'][1:6] if i!=-1]
                    if row['EffectType']=='AddRandEffect':
                        self.assertIn(len(children),(0,1,4))
                        values=Counter()
                        if not children:values[()]=Fraction(1)
                        for child in children:
                            for statuses,p in walk(child,depth+1).items():values[statuses]+=p/len(children)
                    elif row['EffectType']=='AddEffect':
                        self.assertLessEqual(len(children),4)
                        values={():Fraction(1)}
                        for child in children:
                            values={a+b:pa*pb for a,pa in values.items() for b,pb in walk(child,depth+1).items()}
                    else:values={(row['statusCondition'],):Fraction(1)}
                    cache[eid]=values;return values
                observed=walk(root)
                from ability_converter.adapters import AILMENTS
                expected={tuple(s for i,n in enumerate(AILMENTS) if mask & 1<<i
                    for s in (('AttackDown','IntelligenceDown') if n=='Disease' else (n,))):Fraction(n,RESOLUTION)
                    for mask,n in weights(tuple(chances),cap) if n}
                self.assertEqual(dict(observed),expected)
                self.assertLess(len(rows),2500)
                for row in rows.values():self.assertEqual(row['addProbability'],100)

    def test_disease_uses_one_chance_then_paired_native_resistance_checks(self):
        result=self.result([0]*6+[25,0])
        root=result['native']['effects'][0]
        self.assertEqual(root['orderedAilments']['outcomes'],[{'mask':0,'tickets':49152},{'mask':64,'tickets':16384}])
        self.assertEqual([e['set']['statusCondition'] for e in root['ailmentEffects'][0]['effects']],['AttackDown','IntelligenceDown'])
        self.assertTrue(all(e['set']['addProbability']==100 for e in root['ailmentEffects'][0]['effects']))

    def test_recipient_and_portable_command_snapshot(self):
        record=source([30]*8,3,code=34);record.data['effects_raw'][0][:2]=[0,3]
        profile=commands.profile(record)
        self.assertTrue(profile['supported'],profile['issues'])
        restored=commands.from_snapshot(json.loads(json.dumps(profile['snapshot'])))
        self.assertEqual(profile['conversion']['native'],restored['conversion']['native'])
        result=profile['conversion'];self.compiled(result)
        self.assertEqual(result['native']['effects'][0]['target']['shape'],'Self')

    def test_seven_candidates_and_intermediate_caps_are_supported(self):
        for cap in range(1,9):self.compiled(self.result([40]*7+[0],cap))

    def test_malformed_controls_vectors_and_caps_fail_closed(self):
        for record in (source([30]*7,code=34),source([30]*8,9,code=34),source([True]*8,code=34)):
            self.assertFalse(self.c.convert(record)['validation']['tableCompatible'])
        record=source(code=34);record.data['effects_raw'][0][3][8]=0
        self.assertFalse(self.c.convert(record)['validation']['tableCompatible'])

    def test_mutated_distribution_and_native_rows_rejected_before_ids(self):
        mutations=[lambda s:s['orderedAilments']['outcomes'][0].update(tickets=1),
            lambda s:s['orderedAilments'].update(resolution=100),
            lambda s:s['orderedAilments'].update(resistancePolicy='retry'),
            lambda s:s['randomSelection'].update(count=4),
            lambda s:s['ailmentEffects'].pop(),
            lambda s:s['ailmentEffects'][0]['effects'][0]['target'].update(shape='Self'),
            lambda s:s['ailmentEffects'][0]['effects'][0]['set'].update(addProbability=50),
            lambda s:s['ailmentEffects'][0]['effects'][0]['set'].update(effectEndActionNum=99),
            lambda s:s['set'].update(ParamList=[1]+[-1]*14),
            lambda s:s.pop('orderedAilments'),lambda s:s.pop('ailmentEffects')]
        for mutate in mutations:
            result=deepcopy(self.result([30]*8,2));mutate(result['native']['effects'][0])
            writer=TableWriter(self.c.native);ledger=deepcopy(writer.ledger)
            with self.assertRaises(ValueError):writer.add(result)
            self.assertEqual(writer.ledger,ledger);self.assertFalse(writer.tables)

    def test_native_template_drift_rejected(self):
        c=Converter();c.native=deepcopy(c.native)
        result=self.result([30]*8,2);spec=deepcopy(result['native']['effects'][0])
        from ability_converter.ordered_ailments import validate
        c.native.effects[11901]['effectEndActionNum']=2
        with self.assertRaises(ValueError):validate(spec,c.native)
        c.native.effects[11901]=deepcopy(self.c.native.effects[11901])
        c.native.effects[1376]['EffectType']='Analyze'
        with self.assertRaisesRegex(ValueError,'bundle template'):validate(spec,c.native)


if __name__=='__main__':unittest.main()
