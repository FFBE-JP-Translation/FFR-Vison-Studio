"""Battle-start-only casts and complete passive arrays retain event ownership."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,commands
from ability_converter.catalog import SourceCatalog
from ability_converter.compiler import TableWriter
from ability_converter.automatic_passives import START_PARAMS
from test_ability_automatic_passives import passive,child


class BattleStartTests(unittest.TestCase):
    def setUp(self):
        self.db=SourceCatalog();self.addCleanup(self.db.close);self.c=Converter(resolver=self.db)

    def convert(self,p=None,future=None,ready=True):
        p=p or passive(103,[200,0,0])
        for r in (p,future or child()):self.db.add(r)
        self.db.finish();r=self.c.convert(p)
        self.assertEqual(r['validation']['tableCompatible'],ready,r['issues'])
        return r

    def test_startup_is_registered_at_begin_battle_and_expires_at_add_effect(self):
        r=self.convert();spec=r['native']['effects'][0]
        self.assertEqual(spec['passiveTiming'],'BeginBattle')
        self.assertEqual(spec['set']['ParamList'],START_PARAMS)
        self.assertEqual((spec['set']['applyTiming'],spec['set']['proceedTiming'],spec['set']['effectEndActionNum']),('AddEffect','AddEffect',1))
        self.assertEqual(spec['automaticPassive']['nativeEvidence']['passiveTemplate'],1049)
        w=TableWriter(self.c.native);w.add(r)
        bundle=w.tables['Skill/DT_PassiveSkillData']['add'][0]['set']['effectBundleList'][0]
        self.assertEqual(bundle['passiveSkillAddTiming'],'BeginBattle')
        self.assertFalse(w.tables['Skill/DT_PassiveSkillData']['add'][0]['set']['bBattleOnly'])
        self.assertIn('At battle start, automatically',TableWriter.description(r))

    def test_startup_and_other_triggers_stay_in_distinct_bundles(self):
        effects=[[0,3,103,[200,0,0]],[0,3,66,[200,100,0]],
                 [0,3,1,[10,0,0,0,0,0,0]],[0,3,104,[200,0,0]]]
        r=self.convert(passive(effects=effects));w=TableWriter(self.c.native);w.add(r)
        bundles=w.tables['Skill/DT_PassiveSkillData']['add'][0]['set']['effectBundleList']
        self.assertEqual([b['passiveSkillAddTiming'] for b in bundles],['BeginBattle','SpawnUnit','SpawnUnit','SpawnUnit'])
        grants=[e['set'] for e in w.tables['Skill/DT_SkillEffectData']['add'] if e['set']['EffectType']=='AutomaticSkill']
        self.assertEqual({g['applyTiming'] for g in grants},{'AddEffect','BeginTurn','Revival'})
        self.assertEqual(len({g['ParamList'][1] for g in grants}),3)

    def test_long_passive_array_retains_all_components_without_a_fixed_cap(self):
        effects=[[0,3,1,[10,0,0,0,0,0,0]] for _ in range(16)]+[[0,3,103,[200,0,0]]]
        r=self.convert(passive(effects=effects));w=TableWriter(self.c.native);w.add(r)
        bundles=w.tables['Skill/DT_PassiveSkillData']['add'][0]['set']['effectBundleList']
        self.assertEqual(len(bundles),17)
        self.assertEqual([b['passiveSkillAddTiming'] for b in bundles],['SpawnUnit']*16+['BeginBattle'])

    def test_startup_snapshot_rebuilds_without_source_files(self):
        p=passive(103,[200,0,0]);self.convert(p)
        profile=commands.profile(p,self.db);rebuilt=commands.from_snapshot(profile['snapshot'])
        self.assertTrue(rebuilt['supported'],rebuilt['issues'])
        self.assertEqual(len(rebuilt['snapshot']['records']),2)
        w=TableWriter(self.c.native);w.add(rebuilt['conversion'])
        self.assertEqual(len(w.tables['Skill/DT_SkillData']['add']),1)

    def test_startup_does_not_silently_drop_child_cost_or_source_controls(self):
        self.convert(future=child(mp_cost=7),ready=False)
        for params in ([200,0,1],[200,1,0],[200,1,1]):
            r=self.c.convert(passive(103,params))
            self.assertFalse(r['validation']['tableCompatible'])
            self.assertEqual(r['components'][0]['semantic']['sourceTrigger'],'battle_start')
            self.assertEqual(r['components'][0]['semantic']['sourceControls'],params[1:])

    def test_startup_contract_tampering_is_rejected_before_allocation(self):
        good=self.convert()
        for mutation in ('birth','missing_birth','binding','persistent','repeat','evidence','passive_owner','availability'):
            r=deepcopy(good);e=r['native']['effects'][0]
            if mutation=='birth':e['passiveTiming']='SpawnUnit'
            elif mutation=='missing_birth':e.pop('passiveTiming')
            elif mutation=='binding':e.pop('automaticPassive')
            elif mutation=='persistent':e['set']['effectEndActionNum']=-1
            elif mutation=='repeat':e['set']['ParamList'][4]=0
            elif mutation=='evidence':e['automaticPassive']['nativeEvidence']['passiveTemplate']=999
            elif mutation=='passive_owner':r['native']['table']='Skill/DT_SkillData'
            elif mutation=='availability':r['native']['set']['bBattleOnly']=True
            w=TableWriter(self.c.native)
            with self.assertRaises(ValueError,msg=mutation):w.add(r)
            self.assertEqual(w.tables,{})

    def test_plain_effect_cannot_acquire_an_unbound_passive_trigger(self):
        r=self.convert(passive(effects=[[0,3,1,[10,0,0,0,0,0,0]]]))
        r['native']['effects'][0]['passiveTiming']='BeginBattle'
        w=TableWriter(self.c.native)
        with self.assertRaisesRegex(ValueError,'source trigger'):w.add(r)
        self.assertEqual(w.tables,{})

    def test_template_drift_does_not_move_cast_to_spawn_unit(self):
        r=self.convert();native=deepcopy(self.c.native)
        native.passives[native.passive_ids[1049]]['effectBundleList'][0]['passiveSkillAddTiming']='SpawnUnit'
        with self.assertRaisesRegex(ValueError,'battle-start passive template'):TableWriter(native).add(r)

    def test_shared_brave_shift_opcodes_are_not_reduced_to_battle_start_only(self):
        for code in (35,56):
            r=self.c.convert(passive(code,[200]))
            self.assertFalse(r['validation']['tableCompatible'])
            self.assertEqual(r['components'][0]['effects'],[])


if __name__=='__main__':unittest.main()
