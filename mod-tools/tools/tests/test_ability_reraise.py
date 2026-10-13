"""Reraise preserves timed private references through export and unit binding."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands,resonance
from ability_converter.compiler import TableWriter


def source(hp=80,turns=3,control=None,shape=1,side=2,sid='27',kind='magic'):
    return SourceRecord('TEST',kind,sid,{'name':'Auto-life',
        'effects_raw':[[shape,side,27,[hp,turns]+([] if control is None else [control])]],
        'attack_frames':[[24]],'attack_damage':[[100]],'mp_cost':12})


def graph(writer,root):
    skills={r['set']['ID']:r['set'] for r in writer.tables['Skill/DT_SkillData']['add']}
    effects={r['set']['ID']:r['set'] for r in writer.tables['Skill/DT_SkillEffectData']['add']}
    grant=effects[skills[root]['effectBundleList'][0]['effectId']]
    child=skills[grant['ParamList'][1]]
    revive,cleanup=[effects[b['effectId']] for b in child['effectBundleList'][:2]]
    return grant,child,revive,cleanup


class ReraiseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()

    def convert(self,**kwargs):
        r=self.c.convert(source(**kwargs));self.assertTrue(r['validation']['tableCompatible'],r['issues']);return r

    def test_private_graph_preserves_hp_duration_and_exact_cleanup(self):
        for hp,turns in ((1,1),(25,2),(80,3),(100,5)):
            r=self.convert(hp=hp,turns=turns);w=TableWriter(self.c.native);sid=w.add(r)
            grant,child,revive,cleanup=graph(w,sid)
            self.assertEqual((grant['applyTiming'],grant['proceedTiming'],grant['effectEndActionNum']),('Reraise','BeginTurn',turns))
            self.assertEqual(revive['ParamList'],[hp]+[-1]*14)
            self.assertEqual(cleanup['ParamList'],[grant['ID']]+[-1]*9+[1]+[-1]*4)
            self.assertNotEqual(grant['ID'],1077);self.assertNotEqual(child['ID'],210240)
            self.assertTrue(grant['isUnremovable'])

    def test_child_remains_private_free_and_available_while_dead(self):
        w=TableWriter(self.c.native);sid=w.add(self.convert());_,child,_,_=graph(w,sid)
        self.assertEqual((child['Cost'],child['belongCommandList'],child['playSequencerId'],child['sequencerIdWhenTargetFriendlies']),(0,[],-1,-1))
        self.assertTrue(child['isAvailableWhenDead']);self.assertTrue(child['isParallelExecutable'])
        self.assertFalse(child['isAliveOnly']);self.assertFalse(child['isMimicEnabled'])
        self.assertEqual(w.tables['Skill/DT_SkillData']['add'][0]['set']['ID'],sid)
        self.assertEqual(len(w.bindings),1)
        general=w.general.patch()['set'][0]['set']['equipperActionVisionSkills']
        self.assertIn(sid,general);self.assertNotIn(child['ID'],general)

    def test_zero_control_and_absent_control_produce_identical_native_graphs(self):
        self.assertEqual(self.convert()['native'],self.convert(control=0)['native'])

    def test_source_duration_above_native_cap_is_explicitly_adapted(self):
        r=self.convert(turns=99999)
        semantic=r['components'][0]['semantic']
        self.assertEqual((semantic['sourceTurns'],semantic['turns']),(99999,10))
        self.assertEqual(r['native']['effects'][0]['set']['effectEndActionNum'],10)
        self.assertIn('capped from 99999',' '.join(r['changes']))
        self.assertIn('for 10 turns',TableWriter.description(r))

    def test_unknown_controls_and_invalid_values_never_emit_partial_reraise(self):
        for kw in ({'control':1},{'control':2},{'control':True},{'control':.5},{'hp':0},{'hp':101},{'hp':.5},{'turns':0},{'turns':1.5}):
            r=self.c.convert(source(**kw));self.assertFalse(r['validation']['tableCompatible'])
            self.assertFalse(r['components'][0]['effects'])

    def test_grant_recipient_and_source_ownership_stay_distinct(self):
        for shape,side,expected in ((0,3,'Self'),(1,2,'SkillTarget'),(2,2,'Group'),(2,1,'Group')):
            r=self.convert(shape=shape,side=side);w=TableWriter(self.c.native);sid=w.add(r)
            root=w.tables['Skill/DT_SkillData']['add'][0]['set']
            self.assertEqual(root['effectBundleList'][0]['TargetType'],expected)
            grant,child,_,_=graph(w,sid)
            self.assertEqual(grant['ParamList'][2],1001)
            self.assertEqual([b['TargetType'] for b in child['effectBundleList'][:2]],['SkillTarget','Self'])
            self.assertEqual(r['components'][0]['semantic']['nativeBinding']['actor'],'grant_recipient')

    def test_duplicate_configuration_shares_complete_graph_and_ledger_is_stable(self):
        w=TableWriter(self.c.native);a=w.add(self.convert());b=w.add(self.convert(sid='28'))
        self.assertEqual(graph(w,a),graph(w,b))
        self.assertEqual(len(w.tables['Skill/DT_SkillEffectData']['add']),3)
        self.assertEqual(len(w.tables['Skill/DT_SkillData']['add']),3)
        replay=TableWriter(self.c.native,deepcopy(w.ledger));self.assertEqual(replay.add(self.convert()),a)
        self.assertEqual(graph(w,a),graph(replay,a))

    def test_different_hp_or_lifetime_cannot_share_cleanup_cycle(self):
        w=TableWriter(self.c.native)
        ids=[w.add(self.convert(sid=str(i),hp=hp,turns=t)) for i,(hp,t) in enumerate(((80,3),(100,3),(80,4)))]
        grants=[graph(w,i)[0]['ID'] for i in ids]
        self.assertEqual(len(set(grants)),3)
        self.assertEqual([graph(w,i)[3]['ParamList'][0] for i in ids],grants)

    def test_missing_or_tampered_graph_rejected_before_allocation(self):
        for mutate in (lambda e:e.pop('reraise'),lambda e:e['set']['ParamList'].__setitem__(1,210240),
                       lambda e:e['set'].__setitem__('effectEndActionNum',-1),lambda e:e['reraise'].__setitem__('hpPercent',0),
                       lambda e:e['target'].__setitem__('state','Dead')):
            r=self.convert();mutate(r['native']['effects'][0]);w=TableWriter(self.c.native)
            with self.assertRaises(ValueError):w.add(r)
            self.assertEqual(w.tables,{});self.assertTrue(all(not x for x in w.ledger.values()))

    def test_native_target_policy_drift_is_detected(self):
        native=deepcopy(self.c.native);native.target_policies[1001]['isAlive']=True
        r=Converter(native=native).convert(source())
        self.assertFalse(r['validation']['tableCompatible']);self.assertIn('target policy',' '.join(r['issues']))

    def test_bundle_overflow_still_materializes_nested_reraise(self):
        record=source();record.data['effects_raw'] += [[1,2,3,[100,0,0,0,3,1]]]*8
        r=self.c.convert(record);self.assertTrue(r['validation']['tableCompatible'],r['issues'])
        w=TableWriter(self.c.native);w.add(r)
        self.assertEqual(sum(e['set']['EffectType']=='AutomaticSkill' for e in w.tables['Skill/DT_SkillEffectData']['add']),1)
        self.assertEqual(len(w.tables['Skill/DT_SkillData']['add']),2)

    def test_snapshot_and_skill_owned_materialization_preserve_private_cycle(self):
        p=commands.profile(source());self.assertTrue(p['supported'],p['issues'])
        restored=commands.from_snapshot(p['snapshot']);self.assertTrue(restored['supported'],restored['issues'])
        tables={}
        def tbl(name):return tables.setdefault(name,{'add':[],'set':[]})
        import make_vision_mod as generator
        root=resonance.materialize(restored,444010,'Fixture',tbl,generator.row_by)
        child=tables['Skill/DT_SkillData']['add'][0]['set']
        effects={r['set']['ID']:r['set'] for r in tables['Skill/DT_SkillEffectData']['add']}
        grant=effects[root['effectBundleList'][0]['effectId']]
        self.assertEqual(grant['ParamList'][1],child['ID'])
        self.assertTrue(600000<=child['ID']<900000)
        self.assertEqual(effects[child['effectBundleList'][1]['effectId']]['ParamList'][0],grant['ID'])
        before=json.dumps(tables,sort_keys=True)
        with self.assertRaisesRegex(ValueError,'Duplicate'):resonance.materialize(restored,444010,'Fixture',tbl,generator.row_by)
        self.assertEqual(json.dumps(tables,sort_keys=True),before)

    def test_description_and_lb_support_profile_preserve_auto_revive(self):
        self.assertIn('one automatic revival with 80% HP for 3 turns',TableWriter.description(self.convert()))
        data={'schema':2,'lbId':'270','name':'Auto-life LB','moveType':0,'elements':[],
              'rawAttackFrames':'24:100','components':[{'index':0,'range':2,'target':2,'type':27,'params':[100,3,0]}]}
        timeline,p=resonance.profile(data)
        self.assertTrue(p['supported'],p['issues']);self.assertEqual(timeline['hitFrames'],[24])
        self.assertEqual(p['set']['magnification'],0)


if __name__=='__main__':unittest.main()
