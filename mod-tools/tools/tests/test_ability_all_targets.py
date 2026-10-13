"""Native All selection preserves both sides through commands and effects."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands
from ability_converter.compiler import TableWriter
from ability_converter.all_targets import EVIDENCE,SETTINGS


def source(effects=None,**data):
    return SourceRecord('TEST','magic','all',{'name':'All-side effect','effects_raw':effects or [[2,4,59,[0]]],
        'attack_frames':[[24]],'attack_damage':[[100]],'mp_cost':12,**data})


class AllTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()

    def convert(self,record=None):
        r=self.c.convert(record or source());self.assertTrue(r['validation']['tableCompatible'],r['issues']);return r

    def test_all_side_dispel_retains_selection_for_both_native_operations(self):
        r=self.convert();n=r['native']
        self.assertEqual(n['allTargeting'],EVIDENCE)
        for k,v in SETTINGS.items():self.assertEqual(n['set'][k],v)
        self.assertEqual([e['targetBinding'] for e in n['effects']],['skill_selection']*2)
        w=TableWriter(self.c.native);w.add(r);row=w.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertEqual([b['TargetType'] for b in row['effectBundleList']],['SkillTarget']*2)
        self.assertIn('all allies and enemies',w.description(r))

    def test_all_damage_keeps_source_hits_and_both_side_selection_flags(self):
        r=self.convert(source([[2,4,15,[0,0,0,0,0,400]]],element_inflict=['Dark'],attack_frames=[[12,36]],attack_damage=[[30,70]]))
        row=r['native']['set'];self.assertEqual((row['TargetType'],row['element'],row['DamageType']),('All','Dark','Magic'))
        self.assertEqual(row['hitDamageRatioList'][:2],[.3,.7]);self.assertFalse(row['isSameRelationTargetingDisabled'])
        self.assertFalse(row['isHostilityRelationTargetingDisabled'])
        self.assertIn('all allies and enemies',TableWriter.description(r))

    def test_ally_group_and_caster_effects_stay_separate_under_all_selection(self):
        r=self.convert(source([[2,4,59,[0]],[2,2,3,[20,0,0,0,3]],[0,3,3,[0,0,20,0,3]]]))
        w=TableWriter(self.c.native);w.add(r);row=w.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertEqual([b['TargetType'] for b in row['effectBundleList']],['SkillTarget','SkillTarget','Group','Self'])
        self.assertEqual(row['TargetType'],'All')

    def test_all_status_wrapper_keeps_its_selected_list(self):
        r=self.convert(source([[2,4,6,[100]*8],[2,4,88,[100,3]]]))
        w=TableWriter(self.c.native);w.add(r)
        row=w.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertTrue(all(b['TargetType']=='SkillTarget' for b in row['effectBundleList']))
        self.assertTrue(any(e.get('children') for e in r['native']['effects']))

    def test_random_ailment_wrapper_retains_all_recipients(self):
        r=self.convert(source([[2,4,34,[100]*8+[1,1]]]))
        w=TableWriter(self.c.native);w.add(r)
        self.assertEqual(w.tables['Skill/DT_SkillData']['add'][0]['set']['effectBundleList'][0]['TargetType'],'SkillTarget')

    def test_distinct_damage_applications_use_the_same_all_selection(self):
        record=source([[2,4,1,[0,0,0,0,0,0,300]],[2,4,15,[0,0,0,0,0,600]]],
            attack_frames=[[12],[36]],attack_damage=[[100],[100]])
        r=self.convert(record);self.assertEqual(len(r['native']['applications']),1)
        w=TableWriter(self.c.native);w.add(r)
        self.assertTrue(all(row['set']['TargetType']=='All' for row in w.tables['Skill/DT_SkillData']['add']))
        self.assertEqual(r['native']['effects'][0]['targetBinding'],'skill_selection')
        self.assertEqual(r['native']['sequence']['hitWeights'],[1/3,2/3])

    def test_native_dead_all_selection_is_not_claimed_from_alive_evidence(self):
        r=self.c.convert(source([[2,4,4,[100]]]))
        self.assertFalse(r['validation']['tableCompatible'])

    def test_independent_all_effect_cannot_become_an_empty_all_bundle(self):
        r=self.c.convert(source([[2,1,1,[0,0,0,0,0,0,300]],[2,4,59,[0]]]))
        self.assertFalse(r['validation']['tableCompatible']);self.assertIn('Independent all-side effects',' '.join(r['issues']))

    def test_all_range_does_not_accept_unverified_single_or_random_side_four(self):
        for shape in (0,1,3):
            self.assertFalse(self.c.convert(source([[shape,4,59,[0]]]))['validation']['tableCompatible'])

    def test_command_snapshot_preserves_all_selection(self):
        p=commands.profile(source());self.assertTrue(p['supported'],p['issues'])
        snapshot=commands.from_snapshot(p['snapshot']);r=snapshot['conversion']
        self.assertEqual(r['native']['allTargeting'],EVIDENCE)
        self.assertEqual(snapshot['timeline']['hitFrames'],[24]);self.assertIn('all allies and enemies',snapshot['description'])

    def test_native_evidence_drift_keeps_records_held(self):
        native=deepcopy(self.c.native);native.skills[native.skill_ids[505360]]['isSameRelationTargetingDisabled']=True
        r=Converter(native=native).convert(source());self.assertFalse(r['validation']['tableCompatible'])
        self.assertIn('evidence changed',' '.join(r['issues']))

    def test_tampered_selection_or_bundle_is_rejected_before_allocation(self):
        for mutate in (lambda n:n.pop('allTargeting'),lambda n:n['set'].__setitem__('isSameRelationTargetingDisabled',True),
            lambda n:n['set'].__setitem__('isTargetIgnoreSelf',True),lambda n:n['set'].__setitem__('TargetType','Group'),
            lambda n:n['effects'][0].pop('targetBinding'),lambda n:n['effects'][0]['targetBindingEvidence'].__setitem__('livingOnly',False),
            lambda n:n['effects'][0]['target'].__setitem__('ignoreSelf',True)):
            r=self.convert();mutate(r['native']);w=TableWriter(self.c.native)
            with self.assertRaises(ValueError):w.add(r)
            self.assertEqual(w.tables,{});self.assertTrue(all(not ids for ids in w.ledger.values()))


if __name__=='__main__':unittest.main()
