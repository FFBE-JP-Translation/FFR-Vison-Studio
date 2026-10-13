"""Distinct source damage formulas retain one budget and private native rows."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter, SourceRecord
from ability_converter import commands, resonance
from ability_converter.catalog import SourceCatalog
from ability_converter.compiler import TableWriter

PHYSICAL=[2,1,1,[0,0,0,0,0,0,500]]
MAGIC=[2,1,15,[0,0,0,0,0,1000,0]]
HEAL=[2,2,2,[0,0,1000,200,100]]

def source(effects=None, kind="ability", sid="composition", **data):
    return SourceRecord("TEST",kind,sid,{"name":"Mixed arts","effects_raw":deepcopy(effects or [PHYSICAL,MAGIC]),
        "cost":{"MP":10},"attack_frames":[[12,24],[18,36]],"attack_damage":[[20,80],[50,50]],**data})


class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()

    def convert(self,record):
        r=self.c.convert(record)
        self.assertTrue(r['validation']['tableCompatible'],r['issues'])
        return r

    def test_mixed_formulas_interleave_at_source_times_with_one_budget(self):
        r=self.convert(source())
        n=r['native'];rows=[n['set'],*[j['set'] for j in n['applications']]]
        self.assertEqual(n['sequence']['hitFrames'],[12,18,24,36])
        self.assertEqual([row['DamageType'] for row in rows],['Physic','Magic','Physic','Magic'])
        for index,(row,share) in enumerate(zip(rows,[1/15,1/3,4/15,1/3])):
            self.assertEqual(row['hitCount'],1)
            self.assertAlmostEqual(row['hitDamageRatioList'][index],share)
            self.assertAlmostEqual(sum(row['hitDamageRatioList']),share)
            self.assertEqual(row['magnification'],self.c.native.power(15,row['DamageType']))
        self.assertEqual([row['Cost'] for row in rows],[15,0,0,0])
        text=TableWriter.description(r)
        self.assertIn('2 hits of physical damage',text)
        self.assertIn('2 hits of magic damage',text)
        self.assertNotIn('AppendDamage',text)

    def test_limit_burst_keeps_cloud_budget_across_all_formulas(self):
        n=self.convert(source(kind='lb'))['native']
        rows=[n['set'],*[j['set'] for j in n['applications']]]
        self.assertTrue(all(r['magnification']==self.c.native.cloud['magnification'] for r in rows))
        self.assertAlmostEqual(sum(r['magnification']*sum(r['hitDamageRatioList']) for r in rows),self.c.native.cloud['magnification'])

    def test_one_heal_between_attack_hits_keeps_its_full_power_and_own_recipients(self):
        for shape,side,binding,who in ((0,3,'caster','the user'),(2,2,'living_group','all allies')):
            with self.subTest(binding=binding):
                p=commands.profile(source([PHYSICAL,[shape,side,*HEAL[2:]]],
                    attack_frames=[[12,24],[18]],attack_damage=[[20,80],[100]]))
                self.assertTrue(p['supported'],p['issues'])
                n=p['conversion']['native'];rows=[n['set'],*[j['set'] for j in n['applications']]]
                self.assertEqual(n['sequence']['hitFrames'],[12,18,24])
                self.assertEqual(n['sequence']['hitWeights'],[.2,0.,.8])
                self.assertEqual(p['timeline']['applicationKinds'],['damage','recovery','damage'])
                self.assertEqual([r['parameterVariationType'] for r in rows],['Decrease','Increase','Decrease'])
                self.assertEqual([r['magnification'] for r in rows],
                                 [self.c.native.power(5,'Physic'),50,self.c.native.power(5,'Physic')])
                self.assertEqual(rows[1]['hitDamageRatioList'][:3],[0.,1.,0.])
                self.assertEqual(rows[1]['breakDamageValue'],0)
                self.assertEqual([r['Cost'] for r in rows],[15,0,0])
                self.assertEqual(n['effects'][0]['targetBinding'],binding)
                self.assertEqual(n['effects'][1]['targetBinding'],'skill_selection')
                self.assertIn(f'Restores HP to {who}.',p['description'])
                self.assertIn('2 hits of physical damage to all enemies',p['description'])
                self.assertNotIn('magic damage',p['description'])
                self.assertEqual(p['timeline']['effectPhases'][0]['recoveryEvidence']['childSkillId'],501530)
                self.assertEqual(commands.from_snapshot(p['snapshot'])['conversion']['native'],n)

    def test_single_attack_then_group_attack_retains_each_target_shape(self):
        r=self.convert(source([[1,1,*PHYSICAL[2:]],MAGIC],attack_frames=[[12],[24]],attack_damage=[[100],[100]]))
        n=r['native'];writer=TableWriter(self.c.native);writer.add(r)
        rows=writer.tables['Skill/DT_SkillData']['add']
        self.assertEqual(rows[0]['set']['TargetType'],'Single')
        self.assertEqual(rows[0]['set']['effectBundleList'][0]['TargetType'],'Group')
        self.assertEqual(rows[0]['set']['effectBundleList'][0]['targetRelation'],'Enemies')
        self.assertEqual(rows[1]['set']['TargetType'],'Group')
        self.assertEqual(n['effects'][0]['targetBinding'],'living_group')
        self.assertIn('physical damage to one enemy',TableWriter.description(r))
        self.assertIn('magic damage to all enemies',TableWriter.description(r))

    def test_mixed_support_requires_both_damage_and_recovery_phase_evidence(self):
        record=source([PHYSICAL,HEAL,[0,3,3,[100,0,0,0,3,1]]],
                      attack_frames=[[12],[24],[36]],attack_damage=[[100]]*3)
        self.convert(record)
        p=commands.profile(record)
        self.assertFalse(p['supported'])
        self.assertIn('No stock recovery-phase binding',' '.join(p['issues']))

    def test_unverified_healing_and_independent_selection_contracts_stay_held(self):
        cases=[source([PHYSICAL,HEAL],attack_frames=[[12],[18,24]],attack_damage=[[100],[50,50]]),
               source([PHYSICAL,HEAL],attack_frames=[[12],[]],attack_damage=[[100],[]]),
               source([PHYSICAL,HEAL,HEAL],attack_frames=[[12],[18],[24]],attack_damage=[[100]]*3),
               source([PHYSICAL,HEAL],attack_frames=[[24],[12]],attack_damage=[[100]]*2),
               source([PHYSICAL,[1,2,*HEAL[2:]]],attack_frames=[[12],[24]],attack_damage=[[100]]*2),
               source([PHYSICAL,[2,5,*HEAL[2:]]],attack_frames=[[12],[24]],attack_damage=[[100]]*2),
               source([PHYSICAL,[2,6,*HEAL[2:]]],attack_frames=[[12],[24]],attack_damage=[[100]]*2)]
        for record in cases:
            with self.subTest(effects=record.data['effects_raw'],frames=record.data['attack_frames']):
                self.assertFalse(self.c.convert(record)['validation']['tableCompatible'])

    def test_wrong_recovery_budget_or_recipient_binding_is_rejected_before_export(self):
        r=self.convert(source([PHYSICAL,HEAL],attack_frames=[[12],[24]],attack_damage=[[100]]*2))
        bad=deepcopy(r);bad['native']['applications'][0]['hitBudget']['share']=.5
        with self.assertRaisesRegex(ValueError,'full independent budget'):TableWriter(self.c.native).add(bad)
        bad=deepcopy(r);bad['native']['effects'][0]['targetBinding']='skill_selection'
        with self.assertRaisesRegex(ValueError,'verified recipients'):TableWriter(self.c.native).add(bad)
        bad=deepcopy(r);bad['native']['applications'][0]['set']['defaultTargetState']='Dead'
        with self.assertRaises(ValueError):TableWriter(self.c.native).add(bad)

    def test_per_portion_critical_rate_and_accuracy_do_not_spread_to_other_hits(self):
        n=self.convert(source([PHYSICAL,[2,1,43,[0,0,500,30]]],
                              attack_frames=[[12],[24]],attack_damage=[[100],[100]]))['native']
        a,b=n['set'],n['applications'][0]['set']
        self.assertEqual((a['criticalHitRate'],a['accuracy']),(3,100))
        self.assertEqual((b['criticalHitRate'],b['accuracy']),(100,70))
        self.assertEqual((sum(a['hitDamageRatioList']),sum(b['hitDamageRatioList'])),(.5,.5))

    def test_inline_children_keep_their_elements_and_parent_cost(self):
        parent=source([[0,3,71,[1,1]],[0,3,71,[2,1]]],cost={'MP':20})
        first=source([PHYSICAL],sid='1',element_inflict=['Fire'],attack_frames=[[12]],attack_damage=[[100]])
        second=source([PHYSICAL],sid='2',element_inflict=['Ice'],attack_frames=[[24]],attack_damage=[[100]])
        with SourceCatalog() as catalog:
            for r in (parent,first,second):catalog.add(r)
            catalog.finish()
            p=commands.profile(parent,catalog)
        self.assertTrue(p['supported'],p['issues'])
        n=p['conversion']['native']
        self.assertEqual((n['set']['element'],n['applications'][0]['set']['element']),('Fire','Ice'))
        self.assertEqual((n['set']['Cost'],n['applications'][0]['set']['Cost']),(30,0))
        self.assertEqual(commands.from_snapshot(json.loads(json.dumps(p['snapshot'])))['conversion']['native'],n)

    def test_support_before_and_after_surrounds_all_appended_calculations(self):
        p=commands.profile(source([[0,3,3,[100,0,0,0,3,1]],PHYSICAL,MAGIC,[0,3,3,[0,100,0,0,3,1]]],
                                  attack_frames=[[10],[12],[24],[30]],attack_damage=[[100]]*4))
        self.assertTrue(p['supported'],p['issues'])
        effects=p['conversion']['native']['effects']
        self.assertEqual([e['set']['EffectType'] for e in effects],['ParameterContinuousVariation','AppendDamage','ParameterContinuousVariation'])
        self.assertEqual([e['activeTiming'] for e in effects],['BeforeDamageCalculation','AfterDamageCalculation','AfterDamageCalculation'])
        self.assertEqual(p['timeline']['hitFrames'],[12,24])

    def test_sixty_applications_extend_bundles_and_global_weight_slots(self):
        n=self.convert(source(attack_frames=[list(range(0,60,2)),list(range(1,60,2))],attack_damage=[[1]*30]*2))['native']
        self.assertEqual(len(n['effects']),59)
        self.assertEqual(n['applications'][-1]['hitNumber'],60)
        self.assertEqual(len(n['applications'][-1]['set']['hitDamageRatioList']),60)
        self.assertAlmostEqual(sum(n['sequence']['hitWeights']),1.)
        w=TableWriter(self.c.native);w.add(self.convert(source(attack_frames=[list(range(0,60,2)),list(range(1,60,2))],attack_damage=[[1]*30]*2)))
        row=w.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertEqual(len(row['effectBundleList']),59)

    def test_private_rows_have_stable_ids_and_no_independent_actor_or_cost_grants(self):
        r=self.convert(source(cost={'MP':10,'LB':20}))
        w=TableWriter(self.c.native);root=w.add(r)
        rows=w.tables['Skill/DT_SkillData']['add']
        child_ids=[row['set']['ID'] for row in rows[1:]]
        effects=w.tables['Skill/DT_SkillEffectData']['add']
        self.assertEqual([e['set']['ParamList'][:2] for e in effects],[[sid,0] for sid in child_ids])
        self.assertEqual(w.general.additions['equipperActionVisionSkills'],[root])
        self.assertEqual(w.general.additions['additionalCostData'],[{'SkillId':root,'costType':'LB','Cost':100}])
        for row in rows[1:]:
            self.assertEqual(row['set']['belongCommandList'],[])
            self.assertEqual(row['set']['playSequencerId'],-1)
            self.assertEqual(row['set']['effectBundleList'],[])
        rebuilt=TableWriter(self.c.native,deepcopy(w.ledger));rebuilt.add(r)
        self.assertEqual(rebuilt.tables,w.tables)

    def test_wrong_budgets_and_extra_child_mechanics_are_rejected_before_export(self):
        r=self.convert(source())
        for field,value in (('Cost',1),('hitCount',2),('belongCommandList',[10]),('effectBundleList',[{}])):
            bad=deepcopy(r);bad['native']['applications'][0]['set'][field]=value
            writer=TableWriter(self.c.native)
            with self.assertRaises(ValueError):writer.add(bad)
            self.assertFalse(writer.tables)
        bad=deepcopy(r);bad['native']['applications'][0]['hitBudget']['offset']=0
        with self.assertRaises(ValueError):TableWriter(self.c.native).add(bad)

    def test_unverified_mixed_targets_recovery_fixed_and_interleaved_support_stay_held(self):
        cases=([PHYSICAL,[2,2,2,[0,0,3000,1800,100]]],
               [PHYSICAL,[1,1,15,[0,0,0,0,0,1000,0]]],
               [PHYSICAL,[2,1,41,[1000]]],
               [PHYSICAL,[0,3,3,[100,0,0,0,3,1]],MAGIC])
        for effects in cases:
            with self.subTest(effects=effects):
                r=self.c.convert(source(effects,attack_frames=[[12],[24],[36]],attack_damage=[[100]]*3))
                self.assertFalse(r['validation']['tableCompatible'])

    def test_changed_native_append_templates_are_not_silently_reused(self):
        c=deepcopy(self.c);c.native.effects[59000]['ParamList'][1]=0
        r=c.convert(source())
        self.assertFalse(r['validation']['tableCompatible'])
        self.assertIn('templates changed',' '.join(r['issues']))

    def test_materialization_keeps_children_private_and_rejects_collisions_atomically(self):
        p=commands.profile(source());self.assertTrue(p['supported'],p['issues'])
        tables={}
        def tbl(rel):return tables.setdefault(rel,{'add':[],'set':[]})
        def row_by(*args):return ('donor',{})
        settings=resonance.materialize(p,444080,'Mixed',tbl,row_by)
        children=tbl('Skill/DT_SkillData')['add']
        self.assertEqual(len(children),3)
        self.assertTrue(all(600000 <= r['set']['ID'] < 900000 for r in children))
        self.assertEqual(len({r['set']['ID'] for r in children}),3)
        self.assertEqual(settings['hitCount'],1)
        before=deepcopy(tables)
        with self.assertRaisesRegex(ValueError,'Duplicate converted application'):
            resonance.materialize(p,444080,'Again',tbl,row_by)
        self.assertEqual(tables,before)


if __name__=='__main__':unittest.main()
