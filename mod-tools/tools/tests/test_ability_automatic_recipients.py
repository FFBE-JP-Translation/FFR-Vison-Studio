"""Automatic children preserve native group recipients and reject lost filters."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,commands,SourceRecord
from ability_converter.catalog import SourceCatalog
from ability_converter.compiler import TableWriter
from test_ability_automatic_passives import passive,child
from test_ability_delayed_actions import source


def group_child(effects=None):
    return child(effects_raw=effects or [[0,3,3,[0,100,0,0,2,1,0]],
        [2,2,3,[100,0,0,0,2,1,0]],[2,1,24,[50,0,0,0,2,1]]])


class AutomaticRecipientTests(unittest.TestCase):
    def compile(self,parent=None,future=None):
        with SourceCatalog() as db:
            p=parent or passive(103,[200,0,0])
            db.add(p);db.add(future or group_child());db.finish()
            c=Converter(resolver=db);r=c.convert(p)
            self.assertTrue(r['validation']['tableCompatible'],r['issues'])
            return c,r,commands.profile(p,db)

    def test_all_four_triggers_preserve_three_distinct_recipient_bundles(self):
        for p in (passive(),passive(103,[200,0,0]),passive(104,[200,0,0]),source()):
            c,r,_=self.compile(p);w=TableWriter(c.native);w.add(r)
            e=next(x['set'] for x in w.tables['Skill/DT_SkillEffectData']['add'] if x['set']['EffectType']=='AutomaticSkill')
            private=next(x['set'] for x in w.tables['Skill/DT_SkillData']['add'] if x['set']['ID']==e['ParamList'][1])
            self.assertEqual([(b['TargetType'],b['targetRelation']) for b in private['effectBundleList']],
                [('Self','Friendlies'),('Group','Friendlies'),('Group','Enemies')])
            self.assertEqual((private['TargetType'],private['defaultTargetRelation']),('Self','Friendlies'))
            self.assertEqual((private['Cost'],private['magnification'],private['playSequencerId']),(0,0,-1))
            self.assertEqual(private['belongCommandList'],[])

    def test_portable_passive_and_delayed_command_snapshots_retain_group_plan(self):
        for p in (passive(103,[200,0,0]),source()):
            c,r,profile=self.compile(p);self.assertTrue(profile['supported'],profile['issues'])
            rebuilt=commands.from_snapshot(profile['snapshot']);self.assertTrue(rebuilt['supported'],rebuilt['issues'])
            key='automaticPassive' if p.kind=='passive' else 'delayedAction'
            self.assertEqual(r['native']['effects'][0][key]['recipientBinding'],
                rebuilt['conversion']['native']['effects'][0][key]['recipientBinding'])
            TableWriter(c.native).add(rebuilt['conversion'])

    def test_group_overflow_children_keep_the_wrappers_recipients(self):
        raw=[[2,2,3,[100,0,0,0,2,1,0]]]*9+[[2,1,24,[50,0,0,0,2,1]]]*3
        c,r,_=self.compile(future=group_child(raw));w=TableWriter(c.native);w.add(r)
        private=w.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertEqual([b['targetRelation'] for b in private['effectBundleList']],['Friendlies']*3+['Enemies'])
        effects={v['set']['ID']:v['set'] for v in w.tables['Skill/DT_SkillEffectData']['add']}
        leaves=[]
        def walk(eid,relation):
            e=effects[eid]
            if e['EffectType']=='AddEffect':
                for child_id in e['ParamList'][1:5]:
                    if child_id>=0:walk(child_id,relation)
            else:leaves.append(relation)
        for b in private['effectBundleList']:walk(b['effectId'],b['targetRelation'])
        self.assertEqual(leaves,['Friendlies']*9+['Enemies']*3)

    def test_single_random_dead_and_filtered_recipients_remain_held(self):
        for raw in ([1,2,3,[100,0,0,0,2,1,0]],[3,1,3,[100,0,0,0,2,1,0]],
                    [5,2,3,[100,0,0,0,2,1,0]],[2,2,4,[100]]):
            with SourceCatalog() as db:
                p=passive();db.add(p);db.add(group_child([raw]));db.finish()
                r=Converter(resolver=db).convert(p)
                self.assertFalse(r['validation']['tableCompatible'],raw)

    def test_missing_or_changed_recipient_plan_is_rejected_before_allocation(self):
        for parent,key in ((passive(),'automaticPassive'),(source(),'delayedAction')):
            c,good,_=self.compile(parent)
            for mutation in ('missing','side','shape','phase','evidence','nested'):
                r=deepcopy(good);binding=r['native']['effects'][0][key]
                if mutation=='missing':binding.pop('recipientBinding')
                elif mutation=='evidence':binding['recipientBinding']['nativeEvidence']['supportSkillId']=1
                else:
                    effect=binding['child']['native']['effects'][1]
                    if mutation=='side':effect['target']['relation']='Enemies'
                    elif mutation=='shape':effect['target']['shape']='Self'
                    elif mutation=='phase':effect['activeTiming']='BeforeDamageCalculation'
                    elif mutation=='nested':effect['children']=[deepcopy(binding['child']['native']['effects'][0])]
                w=TableWriter(c.native)
                with self.assertRaises(ValueError,msg=mutation):w.add(r)
                self.assertEqual(w.tables,{})

    def test_group_template_drift_rejects_export(self):
        c,r,_=self.compile();native=deepcopy(c.native)
        native.skills[native.skill_ids[503550]]['effectBundleList'][1]['TargetType']='Self'
        with self.assertRaisesRegex(ValueError,'group-support template'):TableWriter(native).add(r)

    def test_group_child_costs_are_still_paid_or_held_never_dropped(self):
        future=group_child();future.data['mp_cost']=5
        with SourceCatalog() as db:
            p=passive();db.add(p);db.add(future);db.finish();r=Converter(resolver=db).convert(p)
            self.assertFalse(r['validation']['tableCompatible'])
            self.assertIn('additional resource cost',' '.join(r['issues']))

    def test_delayed_parent_cannot_move_the_acting_owner_to_a_group(self):
        with SourceCatalog() as db:
            p=source(effects=[[2,2,132,[200,0,3,100,0]]]);db.add(p);db.add(group_child());db.finish()
            r=Converter(resolver=db).convert(p)
            self.assertFalse(r['validation']['tableCompatible'])
            self.assertIn('retained caster',' '.join(r['issues']))


if __name__=='__main__':unittest.main()
