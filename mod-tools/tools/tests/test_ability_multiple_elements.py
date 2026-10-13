"""Skill-bound elements preserve complete attacks and exported skill ownership."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands
from ability_converter.compiler import TableWriter
from ability_converter.catalog import SourceCatalog
from ability_converter.multiple_elements import EVIDENCE

def source(elements=None,effects=None,**data):
    return SourceRecord('TEST','ability','elements',{'name':'Elemental strike',
        'effects_raw':effects or [[1,1,1,[0,0,0,0,0,0,600]]],
        'element_inflict':elements or ['Fire','Ice'],'attack_frames':[[12,36]],
        'attack_damage':[[30,70]],'mp_cost':12,**data})

class MultipleElementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()
    def convert(self,record=None):
        r=self.c.convert(record or source());self.assertTrue(r['validation']['tableCompatible'],r['issues']);return r

    def test_physical_elements_share_original_weights_power_and_cost(self):
        r=self.convert();one=self.convert(source(['Fire']))
        self.assertEqual(r['native']['set'],one['native']['set'])
        self.assertEqual(r['native']['sequence'],one['native']['sequence'])
        self.assertEqual(r['native']['multipleElements'],{'elements':['Fire','Ice'],'nativeEvidence':EVIDENCE})
        self.assertIn('Fire/Ice physical damage',TableWriter.description(r))
        self.assertNotIn('Adds Ice',TableWriter.description(r))

    def test_magic_all_eight_elements_and_aliases(self):
        r=self.convert(source(['Dark','Light','Water','Lightning','Earth','Wind','Ice','Fire','None','Fire'],
            [[2,1,15,[0,0,0,0,0,600]]]))
        self.assertEqual(r['native']['multipleElements']['elements'],['Dark','Light','Water','Thunder','Earth','Wind','Ice','Fire'])
        self.assertEqual(len(r['native']['effects']),7)
        self.assertEqual([e['set']['ParamList'][0] for e in r['native']['effects']],[7,6,5,4,3,2,1])

    def test_private_effect_id_filter_matches_destination_skill(self):
        r=self.convert();w=TableWriter(self.c.native);sid=w.add(r)
        fx=w.tables['Skill/DT_SkillEffectData']['add'][0]['set']
        self.assertEqual(fx['ParamList'][:2],[2,sid])
        self.assertEqual((fx['proceedTiming'],fx['effectEndActionNum'],fx['isUnremovable']),('SkillEnd',1,True))
        row=w.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertEqual((row['effectBundleList'][0]['TargetType'],row['effectBundleList'][0]['activeSkillAddTiming']),('Self','BeforeDamageCalculation'))

    def test_distinct_skills_do_not_share_element_effect_filters(self):
        a=self.convert();s=source();s.id='other';b=self.convert(s)
        w=TableWriter(self.c.native);ids=[w.add(a),w.add(b)]
        self.assertEqual([r['set']['ParamList'][1] for r in w.tables['Skill/DT_SkillEffectData']['add']],ids)

    def test_deterministic_ledger_and_repeated_export(self):
        r=self.convert();w=TableWriter(self.c.native);sid=w.add(r)
        again=TableWriter(self.c.native,deepcopy(w.ledger));self.assertEqual(again.add(r),sid)
        self.assertEqual(again.tables,w.tables)
        self.assertEqual(r['native']['effects'][0]['set']['ParamList'][1],-1)

    def test_command_snapshot_uses_native_before_damage_binding(self):
        p=commands.profile(source());self.assertTrue(p['supported'],p['issues'])
        restored=commands.from_snapshot(p['snapshot']);self.assertTrue(restored['supported'])
        self.assertEqual(restored['conversion']['native']['multipleElements']['elements'],['Fire','Ice'])
        self.assertEqual(restored['timeline']['hitFrames'],[12,36])

    def test_generated_elements_do_not_consume_support_packing_capacity(self):
        r=self.convert(source(['Fire','Ice','Wind','Earth','Thunder','Water','Light','Dark'],
            [[1,1,1,[0,0,0,0,0,0,600]],[2,1,6,[100]*8]],attack_frames=[[12,36],[40]],attack_damage=[[30,70],[100]]))
        self.assertGreater(len(r['native']['effects']),8)
        TableWriter(self.c.native).add(r)

    def test_same_formula_components_keep_one_shared_damage_row(self):
        r=self.convert(source(effects=[[1,1,1,[0,0,0,0,0,0,300]],[1,1,1,[0,0,0,0,0,0,600]]],
            attack_frames=[[12],[36]],attack_damage=[[100],[100]]))
        self.assertNotIn('applications',r['native'])
        self.assertEqual(r['native']['sequence']['hitWeights'],[1/3,2/3])

    def test_appended_elements_bind_every_interleaved_hit_without_changing_budget(self):
        s=source(effects=[[1,1,1,[0,0,0,0,0,0,300]],[1,1,15,[0,0,0,0,0,600]]],
            attack_frames=[[24,48],[12,36]],attack_damage=[[30,70],[50,50]])
        r=self.convert(s);single=deepcopy(s);single.data['element_inflict']=['Fire'];one=self.convert(single)
        self.assertEqual(r['native']['sequence'],one['native']['sequence'])
        w=TableWriter(self.c.native);w.add(r);rows=w.tables['Skill/DT_SkillData']['add']
        extras=[e['set'] for e in w.tables['Skill/DT_SkillEffectData']['add'] if e['set']['EffectType']=='AddElement']
        self.assertEqual([e['ParamList'][1] for e in extras],[r['set']['ID'] for r in rows])
        self.assertEqual([r['set']['DamageType'] for r in rows],['Magic','Physic','Magic','Physic'])
        for a,b in zip([r['native'],*r['native']['applications']],[one['native'],*one['native']['applications']]):
            self.assertEqual(a['set'],b['set'])
        self.assertTrue(all(e['ParamList'][0]==2 for e in extras))
        self.assertTrue(all(not r['set']['effectBundleList'] and r['set']['Cost']==0 for r in rows[1:]))
        p=commands.profile(s);self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(commands.from_snapshot(p['snapshot'])['conversion']['native'],r['native'])

    def test_child_only_elements_and_shared_component_proxies_keep_exact_owners(self):
        parent=source(effects=[[0,3,71,[1,1]]])
        proxy=source(effects=[[0,3,71,[2,1]],[0,3,71,[3,1]]]);proxy.id='1'
        first=source(['Fire'],attack_frames=[[12]],attack_damage=[[100]]);first.id='2'
        second=source(['Ice','Wind','Dark'],attack_frames=[[24]],attack_damage=[[100]]);second.id='3'
        with SourceCatalog() as db:
            for s in (parent,proxy,first,second):db.add(s)
            db.finish();p=commands.profile(parent,db)
        self.assertTrue(p['supported'],p['issues']);r=p['conversion'];w=TableWriter(self.c.native);w.add(r)
        rows=w.tables['Skill/DT_SkillData']['add'];child_id=rows[1]['set']['ID']
        extras=[e['set'] for e in w.tables['Skill/DT_SkillEffectData']['add'] if e['set']['EffectType']=='AddElement']
        self.assertEqual([e['ParamList'][:2] for e in extras],[[3,child_id],[8,child_id]])
        self.assertNotIn('multipleElements',r['native'])
        self.assertIn('Fire physical damage',p['description']);self.assertIn('Ice/Wind/Dark physical damage',p['description'])
        self.assertEqual(commands.from_snapshot(p['snapshot'])['conversion']['native'],r['native'])

    def test_recovery_never_inherits_damage_elements_or_its_extra_effects(self):
        r=self.convert(source(effects=[[1,1,1,[0,0,0,0,0,0,600]],[0,3,2,[0,0,100,200,100]]],
            attack_frames=[[12,36],[24]],attack_damage=[[30,70],[100]]))
        w=TableWriter(self.c.native);w.add(r);rows=w.tables['Skill/DT_SkillData']['add']
        extras=[e['set'] for e in w.tables['Skill/DT_SkillEffectData']['add'] if e['set']['EffectType']=='AddElement']
        self.assertEqual([e['ParamList'][1] for e in extras],[rows[0]['set']['ID'],rows[2]['set']['ID']])
        self.assertEqual(rows[1]['set']['element'],'None');self.assertNotIn('multipleElements',r['native']['applications'][0])

    def test_appended_owner_and_element_tampering_rejected_before_allocation(self):
        s=source(effects=[[1,1,1,[0,0,0,0,0,0,300]],[1,1,15,[0,0,0,0,0,600]]],
            attack_frames=[[12],[36]],attack_damage=[[100],[100]])
        for mutate in (lambda n:n['effects'][1]['skillElement'].__setitem__('applicationIndex',0),
            lambda n:n['applications'][0].pop('multipleElements'),
            lambda n:n['applications'][0].__setitem__('sourceHitIndex',1),
            lambda n:n['applications'][0]['set'].__setitem__('element','Wind'),
            lambda n:n['effects'][1].__setitem__('activeTiming','AfterDamageCalculation')):
            r=self.convert(s);mutate(r['native']);w=TableWriter(self.c.native)
            with self.assertRaises(ValueError):w.add(r)
            self.assertEqual(w.tables,{});self.assertTrue(all(not x for x in w.ledger.values()))

    def test_unknown_elements_are_not_silently_dropped(self):
        r=self.c.convert(source(['Fire','Invented']))
        self.assertFalse(r['validation']['tableCompatible']);self.assertIn('Unknown source element',' '.join(r['issues']))

    def test_tampering_or_missing_contract_rejected_before_allocation(self):
        for mutate in (lambda n:n.pop('multipleElements'),lambda n:n['effects'].clear(),
            lambda n:n['effects'][0]['set']['ParamList'].__setitem__(1,1234),
            lambda n:n['effects'][0]['set'].__setitem__('proceedTiming','BeginTurn'),
            lambda n:n['effects'][0]['target'].__setitem__('shape','SkillTarget'),
            lambda n:n['effects'][0].__setitem__('activeTiming','AfterDamageCalculation'),
            lambda n:n['set'].__setitem__('element','Dark')):
            r=self.convert();mutate(r['native']);w=TableWriter(self.c.native)
            with self.assertRaises(ValueError):w.add(r)
            self.assertEqual(w.tables,{});self.assertTrue(all(not x for x in w.ledger.values()))

    def test_native_evidence_drift_blocks_conversion(self):
        native=deepcopy(self.c.native);native.effects[1021]['ParamList'][1]=100
        r=Converter(native=native).convert(source())
        self.assertFalse(r['validation']['tableCompatible']);self.assertIn('evidence changed',' '.join(r['issues']))

if __name__=='__main__':unittest.main()
