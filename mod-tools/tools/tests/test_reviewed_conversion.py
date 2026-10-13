"""Policy boundaries for the exhaustive review-stage converter."""
import json
from pathlib import Path
import unittest
from tools.ability_converter.sources import SourceRecord
from tools.ability_converter.catalog import SourceCatalog
from tools.effect_review.conversion.rules import compile_rules
from tools.effect_review.conversion.engine import ReviewedConverter

ROOT=Path(__file__).resolve().parents[2]


class ReviewedConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=Path(json.loads((ROOT/'build/ability-review/current.json').read_text())['directory'])
        cls.rules=compile_rules(cls.folder)['rules']
        cls.converter=ReviewedConverter(cls.rules)

    def record(self,raw,kind='ability',**extra):
        return SourceRecord('TEST',kind,'1',{'name':'Policy fixture','effects_raw':raw,'attack_frames':[[10] for _ in raw],
            'attack_damage':[[100] for _ in raw],**extra})

    def test_compatible_sibling_survives_unknown(self):
        r=self.converter.convert(self.record([[1,1,1,[0,0,0,0,0,0,100]],[1,1,84,[3,0,1]]]))
        self.assertEqual(r['outcome'],'good');self.assertTrue(r['partial'])
        self.assertEqual(r['native']['set']['hitCount'],1)
        self.assertEqual(r['componentAccounting']['total'],2)
        self.assertEqual(r['componentAccounting']['retained'],1)

    def test_roulette_note_overrides_skip(self):
        r=self.converter.convert(self.record([[3,4,73,['none']]]))
        self.assertEqual(r['outcome'],'bad')
        self.assertEqual(r['components'][0]['semantic']['kind'],'requested_random_ffr_skill')
        self.assertIn('selector',r['omissions'][0]['reason'])

    def test_mp_and_resonance_are_one_shot(self):
        for code in (32,33):
            r=self.converter.convert(self.record([[0,3,code,[500 if code==33 else 10]]],kind='passive'))
            self.assertEqual(r['outcome'],'good',r['issues'])
            e=r['native']['effects'][0]
            self.assertEqual(e['passiveTiming'],'BeginBattle')
            self.assertEqual(e['set']['applyTiming'],'AddEffect')
            self.assertEqual(e['set']['effectEndActionNum'],1)
            self.assertEqual(e['resourceBinding']['owner'],'equipping_main_cast')

    def test_bad_subpart_does_not_erase_valid_resource(self):
        r=self.converter.convert(self.record([[1,2,64,[20,-5]]]))
        self.assertEqual(r['outcome'],'good',r['issues']);self.assertTrue(r['partial'])
        self.assertEqual(len(r['native']['effects']),1)
        self.assertEqual(r['native']['effects'][0]['set']['ParamList'][1],1)

    def test_cooldown_expands_partial_child(self):
        with SourceCatalog() as catalog:
            child=self.record([[1,1,1,[0,0,0,0,0,0,100]],[1,1,84,[3,0,1]]]);child.id='2'
            catalog.add(child);catalog.finish()
            engine=ReviewedConverter(self.rules,resolver=catalog)
            r=engine.convert(self.record([[0,3,130,[2,1,[4,4],0]]]))
            self.assertEqual(r['outcome'],'good',r['issues']);self.assertTrue(r['partial'])
            self.assertEqual(r['components'][0]['dependencies'][0]['resolved'],'TEST/ability/2')

    def test_cycle_reported(self):
        with SourceCatalog() as catalog:
            a=self.record([[0,3,130,[2,1,[4,4],0]]]);b=self.record([[0,3,130,[1,1,[4,4],0]]]);b.id='2'
            catalog.add(a);catalog.add(b);catalog.finish()
            r=ReviewedConverter(self.rules,resolver=catalog).convert(a)
            self.assertEqual(r['outcome'],'bad')

    def test_fina_magic_boost_native_pair(self):
        r=self.converter.convert(self.record([[0,3,20,[200,0,0,0]]]))
        self.assertEqual(r['outcome'],'good',r['issues'])
        self.assertEqual([e['template'] for e in r['native']['effects']],[12911,61004])
        self.assertIn('100% more damage',r['summary']);self.assertNotIn('by -50',r['summary'])

    def test_permanent_source_regen_becomes_immediate(self):
        r=self.converter.convert(self.record([[1,2,8,[100,1,1800,-1]]]))
        self.assertEqual(r['outcome'],'good',r['issues'])

    def test_fractional_resource_cannot_round_to_zero(self):
        r=self.converter.convert(self.record([[0,3,33,[30]]],kind='passive'))
        self.assertEqual(r['native']['effects'][0]['set']['ParamList'][0],1)

    def test_enemy_lb_refill_routes_to_main_cast(self):
        r=self.converter.convert(self.record([[2,1,125,[30000,30000]]]))
        self.assertEqual(r['outcome'],'good',r['issues'])
        self.assertEqual(r['native']['set']['defaultTargetRelation'],'Friendlies')
        self.assertEqual(r['native']['effects'][0]['target']['shape'],'Group')
        self.assertEqual(r['sourceRaw'][0][:2],[2,1])

    def test_unknown_cost_not_lost(self):
        r=self.converter.convert(self.record([[1,1,1,[0,0,0,0,0,0,100]]],cost={'unknown':2}))
        self.assertEqual(r['outcome'],'bad')
        self.assertTrue(any('Unknown source resource costs' in i for i in r['issues']))


if __name__=='__main__':unittest.main()
