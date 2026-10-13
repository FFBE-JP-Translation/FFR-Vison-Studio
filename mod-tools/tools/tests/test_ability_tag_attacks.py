"""Tag behavior keeps attack budgets and binds stagger only to its own rows."""
from copy import deepcopy
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands
from ability_converter.compiler import TableWriter
from ability_converter.catalog import SourceCatalog
from ability_converter.graph import SkillGraph
from ability_converter.tag_attacks import EVIDENCE

PHYSICAL=[1,1,1,[0,0,0,0,0,0,600]]
MAGIC=[1,1,15,[0,0,0,0,0,600]]

def source(sid='100',kind='ability',increment=1,effects=None,**data):
    return SourceRecord('TEST',kind,sid,{'name':'Tag strike','mp_cost':12,
        'effects_raw':deepcopy(effects or [PHYSICAL,[0,3,165,[int(sid),increment,1,1,1,1]]]),
        'attack_frames':[[12,36],[48]],'attack_damage':[[30,70],[100]],**data})

class TagAttackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()
    def convert(self,s=None,compiler=None):
        r=(compiler or self.c).convert(s or source());self.assertTrue(r['validation']['tableCompatible'],r['issues']);return r

    def test_tag_preserves_damage_power_cost_targets_and_full_timing(self):
        for raw,kind in ((PHYSICAL,'ability'),(MAGIC,'magic'),(MAGIC,'lb')):
            s=source(kind=kind);s.data['effects_raw'][0]=raw
            r=self.convert(s);ordinary=deepcopy(s);ordinary.data['effects_raw'][1]=[0,3,0,[]]
            one=self.convert(ordinary)
            self.assertEqual(r['native']['set'],one['native']['set'])
            self.assertEqual(r['native']['sequence'],one['native']['sequence'])
            self.assertEqual(r['status'],'replaced')
            self.assertEqual(r['native']['tagAttack']['bonusPercent'],10)
            self.assertIn('10% more stagger power',TableWriter.description(r))

    def test_private_effect_contains_final_skill_filter_and_complete_lifetime(self):
        r=self.convert();w=TableWriter(self.c.native);sid=w.add(r)
        e=w.tables['Skill/DT_SkillEffectData']['add'][0]['set']
        self.assertEqual((e['EffectType'],e['ParamList'][:3]),('MulBaseBreakBySkill',[10,sid,-1]))
        self.assertEqual((e['proceedTiming'],e['effectEndActionNum'],e['isUnremovable']),('SkillEnd',1,True))
        self.assertEqual(r['native']['effects'][0]['tagAttack']['nativeEvidence'],EVIDENCE)

    def test_chain_increment_is_bounded_and_intrinsic_source_duration_is_not_a_turn_grant(self):
        for increment in (1,2,100):
            s=source(increment=increment);s.data['effects_raw'][1][3][2]=5
            r=self.convert(s);e=r['native']['effects'][0]
            self.assertEqual(e['set']['ParamList'][0],min(20,increment*10))
            self.assertEqual((e['set']['proceedTiming'],e['set']['effectEndActionNum']),('SkillEnd',1))

    def test_tag_metadata_between_damage_components_does_not_create_an_action(self):
        r=self.convert(source(effects=[PHYSICAL,[0,3,165,[100,1,1,1,1,1]],MAGIC],
            attack_frames=[[12],[18],[24]],attack_damage=[[100]]*3))
        self.assertEqual(r['native']['sequence']['hitFrames'],[12,24])
        self.assertEqual(r['native']['effects'][0]['tagAttack']['applicationIndices'],[0,1])

    def test_nine_id_chunks_cover_long_interleaved_applications_without_extra_damage(self):
        s=source(effects=[PHYSICAL,MAGIC,[0,3,165,[100,1,1,1,1,1]]],
            attack_frames=[list(range(0,20,2)),list(range(1,18,2)),[24]],attack_damage=[[1]*10,[1]*9,[100]])
        r=self.convert(s);n=r['native'];w=TableWriter(self.c.native);w.add(r)
        rows=w.tables['Skill/DT_SkillData']['add'];fx=[e['set'] for e in w.tables['Skill/DT_SkillEffectData']['add'] if e['set']['EffectType']=='MulBaseBreakBySkill']
        self.assertEqual([len(e['tagAttack']['applicationIndices']) for e in n['effects'] if e.get('tagAttack')],[9,9,1])
        self.assertEqual([v for e in fx for v in e['ParamList'][1:10] if v!=-1],[r['set']['ID'] for r in rows])
        self.assertAlmostEqual(sum(n['sequence']['hitWeights']),1.)
        self.assertEqual(len(rows),19);self.assertTrue(all(not row['set']['effectBundleList'] and row['set']['Cost']==0 for row in rows[1:]))

    def test_nested_proxy_keeps_tagged_and_untagged_portions_separate(self):
        tagged=source('200',attack_frames=[[24],[30]],attack_damage=[[100]]*2)
        untagged=source('300',effects=[PHYSICAL],attack_frames=[[12]],attack_damage=[[100]])
        parent=source('100',effects=[[0,3,71,[300,1]],[0,3,71,[200,1]]])
        with SourceCatalog() as db:
            for s in (parent,tagged,untagged):db.add(s)
            db.finish();p=commands.profile(parent,db)
        self.assertTrue(p['supported'],p['issues']);n=p['conversion']['native']
        self.assertNotIn('tagAttack',n)
        self.assertEqual(n['effects'][0]['tagAttack']['applicationIndices'],[1])
        self.assertEqual(commands.from_snapshot(p['snapshot'])['conversion']['native'],n)
        self.assertEqual(n['applications'][0]['tagAttack']['sourceGrants'][0]['source'],tagged.key)

    def test_parent_and_inline_child_tags_share_one_capped_bonus(self):
        child=source('200',increment=2)
        parent=source('100',increment=2,effects=[[0,3,71,[200,1]],[0,3,165,[100,2,1,1,1,1]]])
        with SourceCatalog() as db:
            db.add(parent);db.add(child);db.finish();r=self.convert(parent,Converter(resolver=db))
        self.assertEqual(r['native']['tagAttack']['bonusPercent'],20)
        self.assertEqual(len(r['native']['effects']),1)
        self.assertEqual(len(r['native']['tagAttack']['sourceGrants']),2)

    def test_recovery_is_never_tagged(self):
        r=self.convert(source(effects=[PHYSICAL,[0,3,2,[0,0,100,200,100]],[0,3,165,[100,1,1,1,1,1]]],
            attack_frames=[[12,36],[24],[48]],attack_damage=[[30,70],[100],[100]]))
        self.assertEqual(r['native']['effects'][0]['tagAttack']['applicationIndices'],[0,2])
        self.assertNotIn('tagAttack',r['native']['applications'][0])

    def test_multi_element_tag_attack_keeps_both_private_contracts(self):
        s=source(element_inflict=['Fire','Ice','Dark']);p=commands.profile(s)
        self.assertTrue(p['supported'],p['issues']);r=p['conversion'];w=TableWriter(self.c.native);sid=w.add(r)
        effects=[e['set'] for e in w.tables['Skill/DT_SkillEffectData']['add']]
        self.assertEqual([e['EffectType'] for e in effects],['MulBaseBreakBySkill','AddElement','AddElement'])
        self.assertTrue(all(e['ParamList'][1]==sid for e in effects))

    def test_unknown_layout_control_identity_targets_and_missing_damage_stay_held(self):
        cases=[]
        for index,value in ((0,200),(1,0),(1,1.5),(3,0),(4,2),(5,-1)):
            s=source();s.data['effects_raw'][1][3][index]=value;cases.append(s)
        s=source();s.data['effects_raw'][1][3].append(0);cases.append(s)
        s=source();s.data['effects_raw'][1][0:2]=[2,2];cases.append(s)
        cases.append(source(effects=[[0,3,165,[100,1,1,1,1,1]]]))
        cases.append(source(effects=[[1,1,41,[300]],[0,3,165,[100,1,1,1,1,1]]]))
        for s in cases:self.assertFalse(self.c.convert(s)['validation']['tableCompatible'],s.data)

    def test_timed_and_global_grants_are_decoded_without_becoming_unrestricted_tags(self):
        for ids in (0,[100],[100,200]):
            s=source();s.data['effects_raw'][1][3][0]=ids;r=self.c.convert(s)
            self.assertFalse(r['validation']['tableCompatible']);self.assertTrue(r['validation']['sourceDecoded'])
            self.assertIn('Timed tag grants',' '.join(r['issues']))
            self.assertFalse(r['native'].get('tagAttack'))

    def test_tampered_filter_phase_budget_and_derived_binding_rejected_before_allocation(self):
        for mutate in (lambda n:n.pop('tagAttack'),lambda n:n['effects'].clear(),
            lambda n:n['effects'][0]['tagAttack'].__setitem__('applicationIndices',[1]),
            lambda n:n['effects'][0]['set']['ParamList'].__setitem__(1,1234),
            lambda n:n['effects'][0]['set'].__setitem__('proceedTiming','BeginTurn'),
            lambda n:n['effects'][0].__setitem__('activeTiming','AfterDamageCalculation'),
            lambda n:n['tagAttack'].__setitem__('bonusPercent',100)):
            r=self.convert();mutate(r['native']);w=TableWriter(self.c.native)
            with self.assertRaises(ValueError):w.add(r)
            self.assertEqual(w.tables,{});self.assertTrue(all(not v for v in w.ledger.values()))

    def test_deterministic_ledger_snapshot_and_native_drift(self):
        r=self.convert();w=TableWriter(self.c.native);sid=w.add(r);again=TableWriter(self.c.native,deepcopy(w.ledger))
        self.assertEqual(again.add(r),sid);self.assertEqual(w.tables,again.tables)
        p=commands.profile(source());self.assertTrue(commands.from_snapshot(json.loads(json.dumps(p['snapshot'])))['supported'])
        n=deepcopy(self.c.native);n.effects[15113]['ParamList'][0]=100
        self.assertFalse(Converter(native=n).convert(source())['validation']['tableCompatible'])

    def test_tag_graph_references_never_execute_and_self_lb_retains_its_level(self):
        a=source('100',kind='lb');a.level='1';b=deepcopy(a);b.level='40'
        foreign=source('200',effects=[PHYSICAL,[0,3,165,[[100],1,3,1,1,1]]])
        for use_catalog in (False,True):
            with SourceCatalog() as db:
                for s in (a,b,foreign):db.add(s)
                db.finish();g=SkillGraph()
                for s in (a,b,foreign):g.add(self.c.convert(s))
                graph=g.resolve(db if use_catalog else None)
                self.assertFalse(graph['missing']);self.assertFalse(graph['cycles']);self.assertFalse(graph['ambiguous'])
                self.assertEqual([(e['from'],e['to']) for e in graph['edges']],[(a.key,a.key),(b.key,b.key),(foreign.key,b.key)])

if __name__=='__main__':unittest.main()
