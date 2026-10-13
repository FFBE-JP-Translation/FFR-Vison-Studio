"""Delayed support retains its countdown, source child and private ownership."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands
from ability_converter.catalog import SourceCatalog
from ability_converter.compiler import TableWriter
from ability_converter.delayed_actions import PARAMS,EVIDENCE


def source(sid='100',effects=None,kind='ability',**data):
    return SourceRecord('TEST',kind,sid,{'name':'Delayed support' if sid=='100' else 'Future ward',
        'mp_cost':12 if sid=='100' else 0,'effects_raw':effects or [[0,3,132,[200,0,3,100,0,19]]],
        'attack_frames':[[12]],'attack_damage':[[100]],'move_type':0,**data})


def child(sid='200',**data):
    return source(sid,[[0,3,3,[100,0,0,0,2,1,0]]],attack_frames=[[90]],**data)


class DelayedActionTests(unittest.TestCase):
    def setUp(self):
        self.db=SourceCatalog();self.addCleanup(self.db.close)
        self.c=Converter(resolver=self.db)

    def convert(self,parent=None,children=None,ready=True):
        parent=parent or source()
        for s in [parent,*(children if children is not None else [child()])]:self.db.add(s)
        self.db.finish();r=self.c.convert(parent)
        if ready:self.assertTrue(r['validation']['tableCompatible'],r['issues'])
        else:self.assertFalse(r['validation']['tableCompatible'])
        return r

    def test_private_countdown_preserves_chance_child_and_native_clock(self):
        p=source(effects=[[0,3,132,[200,0,3,65,0,19]]]);r=self.convert(p)
        spec=r['native']['effects'][0]
        self.assertEqual(spec['set']['ParamList'],PARAMS)
        self.assertEqual((spec['set']['applyTiming'],spec['set']['proceedTiming'],spec['set']['effectEndActionNum']),('BeginTurn','BeginTurn',3))
        self.assertEqual((spec['set']['statusCondition'],spec['set']['activationProbability'],spec['set']['addProbability']),('None',65,100))
        self.assertEqual(spec['delayedAction']['nativeEvidence'],EVIDENCE)
        self.assertEqual(r['components'][0]['expanded']['source']['key'],'TEST/ability/200')
        self.assertIn('After 3 turns, 65% chance',TableWriter.description(r))

    def test_export_keeps_root_first_and_child_free_private_alive_only(self):
        r=self.convert();w=TableWriter(self.c.native);root=w.add(r)
        rows=w.tables['Skill/DT_SkillData']['add'];self.assertEqual(len(rows),2)
        parent,private=[x['set'] for x in rows]
        self.assertEqual((parent['ID'],parent['Cost']),(root,r['native']['set']['Cost']))
        self.assertEqual(private['Cost'],0);self.assertEqual(private['belongCommandList'],[])
        self.assertTrue(private['isParallelExecutable']);self.assertTrue(private['isAliveOnly'])
        self.assertFalse(private['isAvailableWhenDead']);self.assertFalse(private['isMimicEnabled'])
        self.assertEqual(private['playSequencerId'],-1)
        grant=next(x['set'] for x in w.tables['Skill/DT_SkillEffectData']['add'] if x['set']['EffectType']=='AutomaticSkill')
        self.assertEqual(grant['ParamList'][1],private['ID'])
        self.assertIn(private['ID'],w.general.additions['equipperActionVisionSkills'])

    def test_parent_frame_does_not_follow_future_child_frame(self):
        p=source();self.convert(p)
        profile=commands.profile(p,self.db);self.assertTrue(profile['supported'],profile['issues'])
        self.assertEqual(profile['timeline']['hitFrames'],[12])

    def test_snapshot_contains_and_rebuilds_the_delayed_child(self):
        p=source();self.convert(p);snap=commands.profile(p,self.db)['snapshot']
        self.assertEqual({s['id'] for s in snap['records']},{'100','200'})
        resolver=commands.SnapshotResolver(snap)
        r=Converter(resolver=resolver).convert(resolver.root)
        self.assertTrue(r['validation']['tableCompatible'],r['issues'])
        self.assertEqual(r['native']['effects'][0]['delayedAction']['child']['source']['id'],'200')

    def test_damage_parent_keeps_its_own_timeline_and_power(self):
        p=source(effects=[[1,1,1,[0,0,0,0,0,0,600]],[0,3,132,[200,0,1,100,0]]],
            attack_frames=[[12,36],[80]],attack_damage=[[30,70],[100]])
        r=self.convert(p);self.assertEqual(r['native']['sequence']['hitFrames'],[12,36])
        self.assertEqual(r['native']['sequence']['hitWeights'],[.3,.7])
        self.assertEqual(r['native']['effects'][0]['activeTiming'],'AfterDamageCalculation')
        w=TableWriter(self.c.native);w.add(r)
        self.assertEqual(w.tables['Skill/DT_SkillData']['add'][1]['set']['magnification'],0)

    def test_nested_support_chain_has_private_links_and_one_parent_cost(self):
        middle=source('200',[[0,3,132,[300,0,2,100,0,9]]]);r=self.convert(children=[middle,child('300')])
        w=TableWriter(self.c.native);w.add(r);rows=[x['set'] for x in w.tables['Skill/DT_SkillData']['add']]
        self.assertEqual(len(rows),3);self.assertEqual([v['Cost'] for v in rows],[r['native']['set']['Cost'],0,0])
        grants=[x['set'] for x in w.tables['Skill/DT_SkillEffectData']['add'] if x['set']['EffectType']=='AutomaticSkill']
        self.assertEqual({g['ParamList'][1] for g in grants},{v['ID'] for v in rows[1:]})

    def test_delayed_cycle_is_held_before_export(self):
        middle=source('200',[[0,3,132,[100,0,1,100,0]]]);r=self.convert(children=[middle],ready=False)
        self.assertIn('cycle',str(r['components'][0]['expanded']).lower())
        with self.assertRaises(ValueError):TableWriter(self.c.native).add(r)

    def test_unknown_controls_and_long_delays_remain_decoded_holds(self):
        for params in ([200,1,1,100,0],[200,0,1,100,1],[200,0,11,100,0]):
            r=self.c.convert(source(effects=[[0,3,132,params]]))
            self.assertFalse(r['validation']['tableCompatible']);self.assertEqual(r['components'][0]['semantic']['kind'],'delayed_action')

    def test_malformed_layouts_and_values_fail_closed(self):
        for params in ([200,0,1,100],[200,0,1,100,0,0,0],[0,0,1,100,0],[200,0,0,100,0],
                       [200,0,1,101,0],[200,0,1,100,2],[200,0,1,100,0,-1],[200,0,1.5,100,0]):
            self.assertFalse(self.c.convert(source(effects=[[0,3,132,params]]))['validation']['tableCompatible'])

    def test_grants_to_other_actors_are_not_reinterpreted_as_self(self):
        for target in ([1,1],[1,2],[2,2],[2,1]):
            r=self.c.convert(source(effects=[[*target,132,[200,0,1,100,0]]]))
            self.assertIn('retained caster',str(r['issues']))

    def test_additional_child_cost_is_not_dropped(self):
        r=self.convert(children=[child(mp_cost=7)],ready=False)
        self.assertIn('additional resource cost',str(r['issues']))

    def test_child_damage_recovery_and_other_recipients_remain_held(self):
        for raw in ([1,1,1,[0,0,0,0,0,0,600]],[2,2,2,[0,0,2500,1800,100]],[1,2,3,[100,0,0,0,2,1,0]]):
            with SourceCatalog() as db:
                p=source();db.add(p);db.add(source('200',[raw]));db.finish()
                r=Converter(resolver=db).convert(p);self.assertFalse(r['validation']['tableCompatible'])

    def test_private_countdown_tampering_is_rejected_before_allocation(self):
        good=self.convert()
        for mutation in ('binding','lifetime','child_id','cost','target','evidence','chance'):
            r=deepcopy(good);e=r['native']['effects'][0]
            if mutation=='binding':e.pop('delayedAction')
            elif mutation=='lifetime':e['set']['effectEndActionNum']=1
            elif mutation=='child_id':e['delayedAction']['child']['source']['id']='999'
            elif mutation=='cost':e['delayedAction']['child']['sourceMetadata']['mp_cost']=10
            elif mutation=='target':e['target']['shape']='Group'
            elif mutation=='evidence':e['delayedAction']['nativeEvidence']['clock']='wrong'
            elif mutation=='chance':e['set']['activationProbability']=50
            w=TableWriter(self.c.native)
            with self.assertRaises(ValueError,msg=mutation):w.add(r)
            self.assertEqual(w.tables,{})

    def test_native_countdown_template_drift_is_rejected(self):
        r=self.convert();native=deepcopy(self.c.native);native.effects[1071]['ParamList'][7]=0
        with self.assertRaisesRegex(ValueError,'countdown template'):TableWriter(native).add(r)


if __name__=='__main__':unittest.main()
