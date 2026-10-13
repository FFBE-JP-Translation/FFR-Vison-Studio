"""Automatic passive ownership, recurrence, source snapshots and private rows."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands
from ability_converter.catalog import SourceCatalog
from ability_converter.compiler import TableWriter
from ability_converter.automatic_passives import PARAMS,EVIDENCE


def passive(code=66,params=None,effects=None,sid='100'):
    return SourceRecord('TEST','passive',sid,{'name':'Renewing ward',
        'effects_raw':effects or [[0,3,code,params if params is not None else [200,65,0]]]})


def child(raw=None,sid='200',**data):
    return SourceRecord('TEST','ability',sid,{'name':'Future ward','mp_cost':0,
        'effects_raw':[raw or [0,3,3,[100,0,0,0,2,1,0]]],'attack_frames':[[90]],
        'attack_damage':[[100]],'move_type':0,**data})


class AutomaticPassiveTests(unittest.TestCase):
    def setUp(self):
        self.db=SourceCatalog();self.addCleanup(self.db.close)
        self.c=Converter(resolver=self.db)

    def convert(self,p=None,children=None,ready=True):
        p=p or passive()
        for record in [p,*(children if children is not None else [child()])]:self.db.add(record)
        self.db.finish();r=self.c.convert(p)
        self.assertEqual(r['validation']['tableCompatible'],ready,r['issues'])
        return r

    def test_turn_trigger_has_per_event_chance_and_permanent_owner(self):
        r=self.convert();spec=r['native']['effects'][0];row=spec['set']
        self.assertEqual(row['ParamList'],PARAMS)
        self.assertEqual((row['applyTiming'],row['proceedTiming'],row['effectEndActionNum']),('BeginTurn','None',-1))
        self.assertEqual((row['addProbability'],row['activationProbability']),(100,65))
        self.assertTrue(row['isUnremovable']);self.assertEqual(row['statusCondition'],'None')
        self.assertEqual(spec['automaticPassive']['nativeEvidence'],EVIDENCE)
        self.assertIn('start of each turn, 65% chance',TableWriter.description(r))

    def test_revival_uses_revival_event_and_retains_source_controls(self):
        r=self.convert(passive(104,[200,0,0]));c=r['components'][0]
        self.assertEqual(c['semantic']['sourceTrigger'],'on_revival')
        self.assertEqual(c['semantic']['sourceControls'],[0,0])
        self.assertEqual(r['native']['effects'][0]['set']['applyTiming'],'Revival')
        self.assertIn('After revival, automatically',TableWriter.description(r))

    def test_private_export_binds_passive_and_free_child_without_command_entry(self):
        r=self.convert();w=TableWriter(self.c.native);sid=w.add(r)
        parent=w.tables['Skill/DT_PassiveSkillData']['add'][0]['set']
        self.assertEqual(parent['ID'],sid);self.assertEqual(parent['effectBundleList'][0]['passiveSkillAddTiming'],'SpawnUnit')
        private=w.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertEqual(private['Cost'],0);self.assertEqual(private['belongCommandList'],[])
        self.assertTrue(private['isParallelExecutable']);self.assertTrue(private['isAliveOnly'])
        self.assertFalse(private['isAvailableWhenDead']);self.assertFalse(private['isMimicEnabled'])
        self.assertEqual(private['playSequencerId'],-1)
        grant=next(v['set'] for v in w.tables['Skill/DT_SkillEffectData']['add'] if v['set']['EffectType']=='AutomaticSkill')
        self.assertEqual(grant['ParamList'][1],private['ID'])
        self.assertIn(private['ID'],w.general.additions['equipperActionVisionSkills'])

    def test_portable_passive_snapshot_resolves_child_without_source_files(self):
        p=passive();self.convert(p)
        profile=commands.profile(p,self.db);self.assertTrue(profile['supported'],profile['issues'])
        self.assertNotIn('timeline',profile)
        self.assertEqual({r['id'] for r in profile['snapshot']['records']},{'100','200'})
        rebuilt=commands.from_snapshot(profile['snapshot'])
        self.assertTrue(rebuilt['supported'],rebuilt['issues'])
        w=TableWriter(self.c.native);w.add(rebuilt['conversion'])

    def test_multiple_triggers_survive_passive_bundle_packing(self):
        p=passive(effects=[[0,3,66,[200,65,0]],[0,3,104,[200,0,0]],
            [0,3,66,[200,10,0]],[0,3,66,[200,100,0]]])
        r=self.convert(p);w=TableWriter(self.c.native);w.add(r)
        grants=[x['set'] for x in w.tables['Skill/DT_SkillEffectData']['add'] if x['set']['EffectType']=='AutomaticSkill']
        self.assertEqual(len(grants),4);self.assertEqual(len({g['ParamList'][1] for g in grants}),4)

    def test_passive_materializer_stages_active_children_in_the_skill_table(self):
        p=passive();self.convert(p);profile=commands.profile(p,self.db);tables={}
        def tbl(name):return tables.setdefault(name,{'add':[],'set':[]})
        commands.materialize_passive(profile,51400,'TestPassive',tbl,lambda *args: {},'Test')
        grants=[v['set'] for v in tables['Skill/DT_SkillEffectData']['add'] if v['set']['EffectType']=='AutomaticSkill']
        skills=[v['set'] for v in tables['Skill/DT_SkillData']['add']]
        self.assertEqual(len(skills),1);self.assertEqual(grants[0]['ParamList'][1],skills[0]['ID'])
        self.assertEqual(len(tables['Skill/DT_PassiveSkillData']['add']),1)

    def test_passive_materializer_rejects_child_collision_before_adding_effects(self):
        p=passive();self.convert(p);profile=commands.profile(p,self.db)
        tables={}
        def tbl(name):return tables.setdefault(name,{'add':[],'set':[]})
        commands.materialize_passive(profile,51400,'TestPassive',tbl,lambda *args: {},'Test')
        tables['Skill/DT_SkillEffectData']['add'].clear()
        tables['Skill/DT_PassiveSkillData']['add'].clear()
        with self.assertRaisesRegex(ValueError,'Duplicate converted application'):
            commands.materialize_passive(profile,51400,'TestPassive',tbl,lambda *args: {},'Test')
        self.assertEqual(tables.get('Skill/DT_SkillEffectData',{}).get('add',[]),[])
        self.assertEqual(tables['Skill/DT_PassiveSkillData']['add'],[])

    def test_native_zero_chance_remains_zero_instead_of_becoming_unconditional(self):
        r=self.convert(passive(params=[200,0]));w=TableWriter(self.c.native);w.add(r)
        self.assertEqual(r['native']['effects'][0]['set']['activationProbability'],0)

    def test_unknown_controls_remain_structured_holds(self):
        for code,params in ((66,[200,100,1]),(104,[200,0,1]),(104,[200,1,0])):
            r=self.c.convert(passive(code,params))
            self.assertFalse(r['validation']['tableCompatible'])
            self.assertEqual(r['components'][0]['semantic']['kind'],'automatic_passive')
            self.assertIn('Nonzero',str(r['issues']))

    def test_malformed_parameters_fail_closed(self):
        for code,params in ((66,[]),(66,[200]),(66,[200,100,0,0]),(66,[0,100]),
                (66,[200,101]),(66,[200,-1]),(66,[200,50.5]),(104,[200,0]),(104,[200,0,False])):
            self.assertFalse(self.c.convert(passive(code,params))['validation']['tableCompatible'])

    def test_child_cost_and_other_recipients_or_actions_are_not_discarded(self):
        for c in (child(mp_cost=5),child([1,2,3,[100,0,0,0,2,1,0]]),
                child([1,1,1,[0,0,0,0,0,0,600]]),child([0,3,8,[1000,0,0]])):
            with SourceCatalog() as db:
                p=passive();db.add(p);db.add(c);db.finish()
                r=Converter(resolver=db).convert(p)
                self.assertFalse(r['validation']['tableCompatible']);self.assertIn('expanded',r['components'][0])

    def test_missing_revision_and_passive_child_are_held(self):
        r=self.convert(children=[],ready=False);self.assertIn('Missing',str(r['issues']))
        with SourceCatalog() as db:
            p=passive();db.add(p);db.add(passive(effects=[[0,3,1,[10,0,0,0,0,0,0]]],sid='200'));db.finish()
            self.assertFalse(Converter(resolver=db).convert(p)['validation']['tableCompatible'])

    def test_private_binding_tampering_fails_before_allocation(self):
        good=self.convert()
        for mutation in ('binding','chance','timing','repeat','cost','target','evidence','child_id','owner'):
            r=deepcopy(good);e=r['native']['effects'][0]
            if mutation=='binding':e.pop('automaticPassive')
            elif mutation=='chance':e['set']['activationProbability']=100
            elif mutation=='timing':e['set']['applyTiming']='EndTurn'
            elif mutation=='repeat':e['set']['ParamList'][4]=1
            elif mutation=='cost':e['automaticPassive']['child']['sourceMetadata']['mp_cost']=10
            elif mutation=='target':e['target']['shape']='Group'
            elif mutation=='evidence':e['automaticPassive']['nativeEvidence']['actor']='caster'
            elif mutation=='child_id':e['automaticPassive']['child']['source']['id']='999'
            elif mutation=='owner':r['native']['table']='Skill/DT_SkillData'
            w=TableWriter(self.c.native)
            with self.assertRaises(ValueError,msg=mutation):w.add(r)
            self.assertEqual(w.tables,{})

    def test_native_template_or_enum_drift_is_rejected(self):
        r=self.convert()
        for kind in ('template','enum'):
            n=deepcopy(self.c.native)
            if kind=='template':n.effects[1071]['ParamList'][7]=0
            else:n.inventory['enums']['eSkillTiming']['Revival']=52
            with self.assertRaises(ValueError):TableWriter(n).add(r)


if __name__=='__main__':unittest.main()
