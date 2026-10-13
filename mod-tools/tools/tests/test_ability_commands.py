"""Structured unit imports, source snapshots, native grants and command events."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
sys.path.insert(0, str(ROOT/"tools/devui"))
from ability_converter import commands, Converter, SourceRecord
from ability_converter.catalog import SourceCatalog
from ability_converter.studio import StudioResolver
import autoport
import ffbe_catalog
import make_vision_mod as generator
import ffbe_resonance as sequence
import test_ffbe_resonance as sequence_tests


def ability(sid="1", effects=None, kind="ability", **data):
    return SourceRecord("GL_2024", kind, sid, {"name":"Stone Killer", "cost":{"MP":12},
        "effects_raw":effects or [[2,1,40,[0,0,0,0,0,0,0,0,500,500]]],
        "attack_frames":[[12,36]], "attack_damage":[[25,75]], "move_type":0, **data})


def entry(record):
    return {"id":int(record.id), "kind":record.kind.upper(), "name":record.data["name"],
            "effects":["Completely misleading English text"], "sourceRecord":asdict(record)}


def unit():
    return {"key":"structured-fixture", "custom":{"schema":1}, "id":13500, "jp":"StructuredFixture", "command":{"id":999},
            "ffbe":{"id":"123456789"}, "skills":{}, "awakening":[[],[],[],[]], "synchro":[]}


class ImportTests(unittest.TestCase):
    def test_advancing_spell_finishes_movement_before_its_cast_phase(self):
        profile = commands.profile(ability(move_type=1))
        plan = commands.schedule(profile,485000,2.,'magic_attack')
        motions = {e['set']['Unit_PlayAnimByName_AnimationName']:e['time'] for e in plan['events']
                   if e['set']['EventType'] == 'UnitPlayAnimByName'}
        self.assertLess(motions['step_front'],motions['magic_idle'])
        self.assertLess(motions['magic_idle'],motions['magic_attack'])
        self.assertLess(motions['magic_attack'],motions['step_back'])
        animations = [e['set'] for e in plan['events'] if e['set']['EventType'] == 'UnitPlayAnimByName']
        self.assertTrue(all(e['Unit_PlayAnimByName_IsOnlyVisionUnit'] and not e['Unit_PlayAnimByName_SkipDualcast'] for e in animations))

    def test_packaged_converter_runs_without_developer_paths_or_game_extraction(self):
        from release.build_release import ship_converter_data
        with tempfile.TemporaryDirectory(prefix="converter-pack-",dir=ROOT/"build") as temporary:
            engine = Path(temporary)
            ship_converter_data(str(engine/"data"))
            shutil.copytree(ROOT/"tools/ability_converter",engine/"tools/ability_converter",
                            ignore=shutil.ignore_patterns("__pycache__","*.pyc"))
            script = "import sys; sys.path.insert(0, sys.argv[1]); from ability_converter import Converter, SourceRecord; " \
                     "c=Converter(); r=c.convert(SourceRecord('PACK','passive','1',{'effects_raw':[[0,3,1,[20,0,0,0,0,0]]]})); " \
                     "assert r['validation']['tableCompatible'], r['issues']; print(c.native.general_path)"
            result = subprocess.run([sys.executable,"-I","-B","-c",script,str(engine/"tools")],
                                    capture_output=True,text=True,encoding="utf8",cwd=engine)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(str(engine),result.stdout)

    def test_unit_archive_includes_immediate_child_sources(self):
        from release import unit_assets
        root = ability(effects=[[0,3,71,[2,1]]])
        child = ability("2")
        tables = {"skills_ability":{"1":root.data,"2":child.data},"skills_magic":{},"skills_passive":{}}
        raw = {**tables,"skills_ability":{"1":root.data}}
        with patch.object(ffbe_catalog,"sources",return_value={"GLW":tables}):
            unit_assets.include_ability_children("GLW",raw)
        self.assertEqual(raw["skills_ability"]["2"],child.data)

    def test_individual_import_endpoint_returns_draft_without_saving(self):
        from fastapi.testclient import TestClient
        import server
        original = unit()
        with patch.object(server,"save_spec") as save:
            response = TestClient(server.app).post("/api/ffbe/ability/import",json={
                "unit":original, "ability":entry(ability()), "region":"GLW", "effectChoices":{"active:40":"proposed"}})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(response.json()["skills"]),1)
            self.assertFalse(original["skills"])
            save.assert_not_called()
            bad = TestClient(server.app).post("/api/ffbe/ability/import",json={
                "unit":original, "ability":entry(ability(effects=[[2,1,999999,[1]]])), "region":"GLW"})
            self.assertEqual(bad.status_code,200)
            self.assertEqual(len(bad.json()["conversionReview"]),1)
            save.assert_not_called()

    def test_snapshot_is_portable_and_children_keep_original_revision(self):
        root = ability(effects=[[0,3,71,[2,1]]], cost={"MP":17})
        child = ability("2")
        with SourceCatalog() as catalog:
            catalog.add(root); catalog.add(child); catalog.finish()
            p = commands.profile(root,catalog)
        self.assertTrue(p["supported"],p["issues"])
        self.assertEqual(len(p["snapshot"]["records"]),2)
        rebuilt = commands.from_snapshot(json.loads(json.dumps(p["snapshot"])))
        self.assertEqual(rebuilt["set"],p["set"])
        self.assertEqual(rebuilt["set"]["Cost"],26)
        wrong = deepcopy(p["snapshot"])
        wrong["records"][1]["source"] = "JP_2024"
        self.assertFalse(commands.from_snapshot(wrong)["supported"])

    def test_support_proxy_uses_child_application_frame(self):
        root = ability(effects=[[0,3,71,[2,1]]],attack_frames=[[]])
        child = ability("2",[[0,3,3,[0,60,0,0,99999,1]], [0,3,119,[30,1,100,99999,1]]],attack_frames=[[120]])
        with SourceCatalog() as catalog:
            catalog.add(root); catalog.add(child); catalog.finish()
            p = commands.profile(root,catalog)
        self.assertTrue(p["supported"],p["issues"])
        self.assertEqual(p["timeline"]["hitFrames"],[120])
        self.assertEqual(p["set"]["DamageType"],"None")
        self.assertEqual(len(p["conversion"]["native"]["effects"]),2)

    def test_archive_resource_dictionary_is_not_lost(self):
        p = commands.profile(ability(cost={"MP":10, "LB":20}))
        self.assertTrue(p["supported"],p["issues"])
        self.assertEqual(p["set"]["Cost"],15)
        self.assertEqual(p["conversion"]["resourceCosts"],[{"costType":"LB","Cost":100}])
        held = commands.profile(ability(cost={"EV":4}))
        self.assertFalse(held["supported"])
        self.assertIn("Esper-gauge", " ".join(held["issues"]))
        archived = commands.profile(ability(cost={"EP":4}))
        self.assertEqual(archived["conversion"]["costs"]["ev_cost"],4)
        self.assertFalse(archived["supported"])
        unknown = commands.profile(ability(cost={"UnknownResource":1}))
        self.assertFalse(unknown["supported"])
        self.assertIn("must not be omitted", " ".join(unknown["issues"]))

    def test_catalog_identity_and_raw_fields_survive_presentation(self):
        r = ability()
        row = ffbe_catalog.skill_record("GLW",1,"skills_ability",r.data)
        source = StudioResolver(ffbe_catalog).record({**entry(r),"sourceRecord":row},"GLW")
        self.assertEqual(source.data["attack_damage"],[[25,75]])
        self.assertEqual(source.data["cost"],{"MP":12})
        with self.assertRaisesRegex(ValueError,"revision"):
            StudioResolver(ffbe_catalog).record(entry(r),"JPW")

    def test_importer_retains_unproven_passives_and_other_held_records(self):
        u = unit()
        cure = ability("2",[[2,2,111,[0,0,0,0,1,0]]],attack_frames=[[18]])
        stone = ability("3",[[0,3,105,[10,200]]],"passive",cost={})
        unknown = ability("4",[[2,1,999999,[1]]])
        damage = ability(effects=[[2,1,1,[0,0,0,0,0,0,500,0]]])
        detail = {"region":"GLW", "abilities":[entry(damage),entry(cure),entry(unknown)], "passives":[entry(stone)]}
        autoport.autoport(u,{},detail)
        self.assertEqual(len(u["skills"]),1)
        self.assertEqual(len(u["convertedPassives"]),0)
        self.assertEqual({r["id"] for r in u["conversionReview"]},{2,3,4})
        held = next(r for r in u["conversionReview"] if r["id"] == 4)
        self.assertEqual(held["snapshot"]["records"][0]["data"]["effects_raw"],unknown.data["effects_raw"])
        autoport.renumber(u,13501)
        self.assertEqual(u["awakening"][0][-1],["ActiveSkill",485100])

    def test_full_grants_do_not_create_unreachable_skills(self):
        u = unit(); u["awakening"] = [[["BaseParameter",5,1] for _ in range(8)] for _ in range(4)]
        held = autoport.import_entry(u,entry(ability(effects=[[2,1,1,[0,0,0,0,0,0,500,0]]])),"GLW")
        self.assertEqual(held["status"],"loadout_full")
        self.assertFalse(u["skills"])
        self.assertFalse(u["ffbeMap"]["skills"])

    def test_mixed_damage_uses_evidenced_native_phases_and_missing_frames_hold(self):
        source = ability(effects=[[2,1,1,[0,0,0,0,0,0,500,0]], [0,3,3,[100,0,0,0,3,1]]])
        p = commands.profile(source)
        self.assertTrue(p["supported"],p["issues"])
        phase = p["timeline"]["effectPhases"][0]
        self.assertEqual(phase["timing"],"AfterDamageCalculation")
        self.assertGreater(phase["evidence"]["skillId"],0)
        self.assertIn("timestamps",p["warnings"][-1])
        source = ability(effects=[[2,2,2,[0,0,0,100,0,1]], [0,3,3,[100,0,0,0,3,1]]])
        self.assertFalse(commands.profile(source)["supported"])
        source = ability(effects=[[2,2,111,[0,0,0,0,1,0]]],attack_frames=[])
        self.assertIn("application frame", " ".join(commands.profile(source)["issues"]))

    def test_recovery_cures_use_recovery_evidence_and_source_application_frame(self):
        heal, cure = [2,2,2,[0,0,3000,1800,100]], [2,2,111,[0,0,0,0,1,0]]
        for effects, timing in (([cure,heal],"BeforeDamageCalculation"), ([heal,cure],"AfterDamageCalculation")):
            with self.subTest(timing=timing):
                p=commands.profile(ability(effects=effects,attack_frames=[[160],[180]],attack_damage=[[100],[100]]))
                self.assertTrue(p["supported"],p["issues"])
                self.assertEqual(p["timeline"]["hitFrames"],[180 if effects[0] == cure else 160])
                self.assertEqual((p["set"]["parameterVariationType"],p["set"]["hitCount"]),("Increase",1))
                phase=p["timeline"]["effectPhases"][0]
                self.assertEqual(phase["timing"],timing)
                native=commands.converter().native
                stock=native.skills[native.skill_ids[phase["evidence"]["skillId"]]]
                self.assertEqual(stock["parameterVariationType"],"Increase")
                self.assertIn("before/after recovery phases",p["warnings"][-1])
                rebuilt=commands.from_snapshot(p["snapshot"])
                self.assertEqual(rebuilt["timeline"],p["timeline"])
        buff=commands.profile(ability(effects=[heal,[0,3,3,[100,0,0,0,3,1]]],
                                      attack_frames=[[160]],attack_damage=[[100]]))
        self.assertFalse(buff["supported"])
        self.assertIn("No stock recovery-phase binding for ParameterContinuousVariation", " ".join(buff["issues"]))
        for effect,expected_kind in (([2,2,17,[100]],"ParameterVariation"), ([2,2,18,[30,3]],"Deffence")):
            with self.subTest(effect=expected_kind):
                p=commands.profile(ability(effects=[heal,effect],attack_frames=[[160]],attack_damage=[[100]]))
                self.assertTrue(p["supported"],p["issues"])
                self.assertEqual(p["timeline"]["effectPhases"][0]["effectType"],expected_kind)
                p=commands.profile(ability(effects=[effect,heal],attack_frames=[[160],[180]],attack_damage=[[100],[100]]))
                self.assertEqual(p["supported"],expected_kind=="ParameterVariation",p["issues"])


class CookedCommandTests(unittest.TestCase):
    """Historical research table fixtures, not Studio/gameplay support claims."""
    run_dt = staticmethod(sequence_tests.CookedResonanceTests.run_dt)
    dump = classmethod(sequence_tests.CookedResonanceTests.dump.__func__)

    @classmethod
    def setUpClass(cls):
        # Keep the existing table/sequence validation independent of Studio's
        # narrower acceptance rules. test_studio_effect_policy covers that gate.
        unfiltered_profile = commands.profile
        research_profile = patch.object(commands, "profile", side_effect=lambda record, resolver=None, **kwargs: unfiltered_profile(record, resolver))
        research_profile.start()
        cls.addClassCleanup(research_profile.stop)
        if not Path(generator.LEGACY,sequence.SHELL+".uasset").is_file():
            raise unittest.SkipTest("Native event shell must be extracted first")
        cls.temp = tempfile.TemporaryDirectory(prefix="converted-command-",dir=ROOT/"build")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name).resolve()
        cls.unit = u = unit()
        stone = ability("3",[[0,3,105,[10,200]]],"passive",cost={})
        cure = ability("2",[[2,2,111,[0,0,0,0,1,0]]],attack_frames=[[18]],cost={"LB":20})
        mixed = ability("5",[[2,1,1,[0,0,0,0,0,0,500,0]], [0,3,3,[100,0,0,0,3,1]]])
        mirage = ability("6",[[0,3,54,[2,4,0]]],attack_frames=[[18]])
        filtered = ability("7",[[2,5,3,[100,0,0,0,3,1]]],attack_frames=[[18]])
        cover = ability("8",[[0,3,96,[1,0,50,70,80,100,3,1,2]]],attack_frames=[[18]])
        guard = ability("9",[[1,5,118,[50,50,100,2,1,0]]],attack_frames=[[18]])
        racial = ability("10",[[2,1,22,[10,0,0,350]]])
        requiem = ability("11",[[2,1,23,[12,0,0,180]]])
        myriad = ability("12",[[0,3,11,[list(range(1,13)),[100]*12,0]]],"passive",cost={})
        weapon = ability("13",[[0,3,75,[8,list(range(1,13)),100,0]]],"passive",cost={})
        rates=[ability(str(sid),[[0,3,code,parameters]],"passive",cost={}) for sid,code,parameters in
            ((14,23,[100,1]),(15,43,[-30]),(16,45,[20]),(17,37,[2000]),
             (18,47,[50,50]),(19,16,[100,0]),(20,43,[25]),(21,43,[-100]))]
        prefix=ability("22",[[2,1,1,[0,0,0,0,0,0,1000]], [0,3,3,[0,60,0,0,3,1]],
                             [0,3,3,[0,0,60,0,3,1]]],attack_frames=[[16,58],[120]],attack_damage=[[20,80],[100]])
        autoport.autoport(u,{}, {"region":"GLW", "abilities":[entry(ability()),entry(cure),entry(mixed),entry(mirage),entry(filtered),entry(cover),entry(guard),entry(racial),entry(requiem),entry(prefix)], "passives":[entry(stone),entry(myriad),entry(weapon),*[entry(r) for r in rates]]})
        tables, clones, jobs = {}, [], []
        def tbl(rel):
            return tables.setdefault(rel,{"asset":generator.DT+rel,"add":[],"set":[]})
        for sid,s in u["skills"].items():
            # Preview settings may be old or edited. Build revalidates sources.
            s["set"].update(Cost=0,DamageType="Physic",magnification=99999)
            with patch.object(generator,"command_motion_seconds",return_value=2.):
                generator.prepare_converted_command(u,s,int(sid),tbl,clones,jobs)
        generator.prepare_converted_passives(u,tbl)
        extended=unit(); extended.update(id=13501,jp="ExtendedFixture")
        frames=list(range(12,12+52*4,4))
        record=ability("23",name="Extended command",attack_frames=[frames],attack_damage=[[1]*51+[53]])
        autoport.autoport(extended,{}, {"region":"GLW","abilities":[entry(record)],"passives":[]})
        cls.extended_spec=next(iter(extended["skills"].values()))
        for sid,s in extended["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=2.):
                generator.prepare_converted_command(extended,s,int(sid),tbl,clones,jobs)
        recovery=unit(); recovery.update(id=13502,jp="RecoveryFixture")
        record=ability("24",[[2,2,111,[0,0,0,0,1,0]], [2,2,2,[0,0,3000,1800,100]],
                             [2,2,111,[0,0,0,1,0,0]]],name="Recovery command",
                       attack_frames=[[100],[160],[180]],attack_damage=[[100],[100],[100]])
        autoport.autoport(recovery,{}, {"region":"GLW","abilities":[entry(record)],"passives":[]})
        cls.recovery_spec=next(iter(recovery["skills"].values()))
        for sid,s in recovery["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=3.):
                generator.prepare_converted_command(recovery,s,int(sid),tbl,clones,jobs)
        composite=unit(); composite.update(id=13503,jp="CompositeFixture")
        record=ability("25",[[2,1,1,[0,0,0,0,0,0,500]], [2,1,15,[0,0,0,0,0,1000,0]]],
                       name="Mixed command",attack_frames=[list(range(12,76,4)),list(range(14,78,4))],
                       attack_damage=[[1]*16]*2)
        autoport.autoport(composite,{}, {"region":"GLW","abilities":[entry(record)],"passives":[]})
        cls.composite_spec=next(iter(composite["skills"].values()))
        for sid,s in composite["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=3.):
                generator.prepare_converted_command(composite,s,int(sid),tbl,clones,jobs)
        mixed_recovery=unit(); mixed_recovery.update(id=13504,jp="AttackRecoveryFixture")
        record=ability("26",[[1,1,1,[0,0,0,0,0,0,500]],[2,1,15,[0,0,0,0,0,1000,0]],
                             [2,2,2,[0,0,1000,200,100]]],name="Attack and recover",
                       attack_frames=[[12,24],[30],[18]],attack_damage=[[20,80],[100],[100]])
        autoport.autoport(mixed_recovery,{}, {"region":"GLW","abilities":[entry(record)],"passives":[]})
        cls.mixed_recovery_spec=next(iter(mixed_recovery["skills"].values()))
        for sid,s in mixed_recovery["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=3.):
                generator.prepare_converted_command(mixed_recovery,s,int(sid),tbl,clones,jobs)
        random=unit();random.update(id=13505,jp="RandomAilmentFixture")
        records=[ability(str(27+i),[[2,1,34,[100]*8+[1,count]]],name=f"Ailment selection {count}",
                         attack_frames=[[24]],attack_damage=[[100]]) for i,count in enumerate((1,8))]
        records.append(ability('500',[[2,1,34,[50]*8+[1,3]]],name='Partial ordered ailments',
            attack_frames=[[24]],attack_damage=[[100]]))
        autoport.autoport(random,{}, {"region":"GLW","abilities":[entry(r) for r in records],"passives":[]})
        cls.random_specs=list(random["skills"].values())
        for sid,s in random["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=2.):
                generator.prepare_converted_command(random,s,int(sid),tbl,clones,jobs)
        reraise=unit();reraise.update(id=13506,jp="ReraiseFixture")
        record=ability("29",[[2,2,27,[80,3,0]]],kind="magic",name="Reraise",attack_frames=[[24]],attack_damage=[[100]])
        autoport.autoport(reraise,{}, {"region":"GLW","abilities":[entry(record)],"passives":[]})
        cls.reraise_spec=next(iter(reraise["skills"].values()))
        for sid,s in reraise["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=2.):
                generator.prepare_converted_command(reraise,s,int(sid),tbl,clones,jobs)
        dispel=unit();dispel.update(id=13507,jp="DispelFixture")
        records=[ability(str(30+i),[[2,1,59,[mode,0]]],kind="magic",name=f"Dispel {mode}",attack_frames=[[24]],attack_damage=[[100]]) for i,mode in enumerate((0,1,2))]
        autoport.autoport(dispel,{}, {"region":"GLW","abilities":[entry(r) for r in records],"passives":[]})
        cls.dispel_specs=list(dispel["skills"].values())
        for sid,s in dispel["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=2.):
                generator.prepare_converted_command(dispel,s,int(sid),tbl,clones,jobs)
        stop=unit();stop.update(id=13508,jp="StopFixture")
        record=ability("33",[[2,1,88,[80,3]]],kind="magic",name="Stop",attack_frames=[[24]],attack_damage=[[100]])
        autoport.autoport(stop,{}, {"region":"GLW","abilities":[entry(record)],"passives":[]})
        cls.stop_spec=next(iter(stop["skills"].values()))
        for sid,s in stop["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=2.):
                generator.prepare_converted_command(stop,s,int(sid),tbl,clones,jobs)
        everyone=unit();everyone.update(id=13509,jp="AllTargetsFixture")
        records=[ability("34",[[2,4,70,[0,0,300,25]]],kind="magic",name="Doomsday",element_inflict=["Dark"],attack_frames=[[12,36]],attack_damage=[[30,70]]),
                 ability("35",[[2,4,59,[0]]],kind="magic",name="Universal Dispel",attack_frames=[[24]],attack_damage=[[100]])]
        autoport.autoport(everyone,{}, {"region":"GLW","abilities":[entry(r) for r in records],"passives":[]})
        cls.all_specs=list(everyone["skills"].values())
        for sid,s in everyone["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=2.):
                generator.prepare_converted_command(everyone,s,int(sid),tbl,clones,jobs)
        elemental=unit();elemental.update(id=13510,jp="MultipleElementsFixture")
        record=ability("36",[[1,1,1,[0,0,0,0,0,0,600]]],name="Elemental strike",element_inflict=["Fire","Ice"],attack_frames=[[12,36]],attack_damage=[[30,70]])
        autoport.autoport(elemental,{}, {"region":"GLW","abilities":[entry(record)],"passives":[]})
        cls.elemental_spec=next(iter(elemental["skills"].values()))
        for sid,s in elemental["skills"].items():
            with patch.object(generator,"command_motion_seconds",return_value=2.):
                generator.prepare_converted_command(elemental,s,int(sid),tbl,clones,jobs)
        combined=unit();combined.update(id=13511,jp='ElementApplicationsFixture')
        records=[ability('37',[[1,1,1,[0,0,0,0,0,0,300]],[1,1,15,[0,0,0,0,0,600]]],
                    name='Elemental combination',element_inflict=['Fire','Ice'],attack_frames=[[12,24],[18,36]],attack_damage=[[20,80],[50,50]]),
                 ability('38',[[2,2,95,[100,50,0,75,0,0,0,0,3,1]]],name='Elemental blessing',attack_frames=[[24]],attack_damage=[[100]])]
        autoport.autoport(combined,{}, {'region':'GLW','abilities':[entry(r) for r in records],'passives':[]})
        cls.combined_element_specs=list(combined['skills'].values())
        for sid,s in combined['skills'].items():
            with patch.object(generator,'command_motion_seconds',return_value=2.):
                generator.prepare_converted_command(combined,s,int(sid),tbl,clones,jobs)
        tag=unit();tag.update(id=13512,jp='TagAttackFixture')
        records=[ability('39',[[1,1,15,[0,0,0,0,0,600]],[0,3,165,[39,1,1,1,1,1]]],
                    name='Tag magic',element_inflict=['Fire','Ice'],attack_frames=[[12,36],[48]],attack_damage=[[30,70],[100]]),
                 ability('40',[[1,1,1,[0,0,0,0,0,0,600]],[1,1,15,[0,0,0,0,0,300]],[0,3,165,[40,1,1,1,1,1]]],
                    name='Tag combination',attack_frames=[list(range(0,20,2)),list(range(1,18,2)),[24]],attack_damage=[[1]*10,[1]*9,[100]])]
        autoport.autoport(tag,{}, {'region':'GLW','abilities':[entry(r) for r in records],'passives':[]})
        cls.tag_specs=list(tag['skills'].values())
        for sid,s in tag['skills'].items():
            with patch.object(generator,'command_motion_seconds',return_value=2.):
                generator.prepare_converted_command(tag,s,int(sid),tbl,clones,jobs)
        delayed=unit();delayed.update(id=13513,jp='DelayedSupportFixture')
        parent=ability('41',[[0,3,132,[42,0,3,65,0,99]]],name='Delayed ward',attack_frames=[[24]],attack_damage=[[100]])
        future=ability('42',[[0,3,3,[100,0,0,0,2,1,0]]],name='Future ward',cost={'MP':0},attack_frames=[[90]],attack_damage=[[100]])
        with SourceCatalog() as catalog:
            catalog.add(parent);catalog.add(future);catalog.finish()
            with patch.object(StudioResolver,'resolve',side_effect=catalog.resolve):
                autoport.autoport(delayed,{}, {'region':'GLW','abilities':[entry(parent)],'passives':[]})
        cls.delayed_spec=next(iter(delayed['skills'].values()))
        for sid,s in delayed['skills'].items():
            with patch.object(generator,'command_motion_seconds',return_value=2.):
                generator.prepare_converted_command(delayed,s,int(sid),tbl,clones,jobs)
        automatic=unit();automatic.update(id=13514,jp='AutomaticPassiveFixture')
        parents=[ability('43',[[0,3,66,[42,65,0]]],'passive',cost={}),
                 ability('44',[[0,3,104,[42,0,0]]],'passive',cost={})]
        with SourceCatalog() as catalog:
            for record in [*parents,future]:catalog.add(record)
            catalog.finish()
            with patch.object(StudioResolver,'resolve',side_effect=catalog.resolve):
                autoport.autoport(automatic,{}, {'region':'GLW','abilities':[],'passives':[entry(r) for r in parents]})
        cls.automatic_specs=list(automatic['convertedPassives'].values())
        generator.prepare_converted_passives(automatic,tbl)
        startup=unit();startup.update(id=13515,jp='BattleStartPassiveFixture')
        parent=ability('45',[[0,3,1,[10,0,0,0,0,0,0]] for _ in range(14)]+[[0,3,103,[42,0,0]]],
                       'passive',cost={})
        with SourceCatalog() as catalog:
            catalog.add(parent);catalog.add(future);catalog.finish()
            with patch.object(StudioResolver,'resolve',side_effect=catalog.resolve):
                autoport.autoport(startup,{}, {'region':'GLW','abilities':[],'passives':[entry(parent)]})
        cls.startup_spec=next(iter(startup['convertedPassives'].values()))
        generator.prepare_converted_passives(startup,tbl)
        grouped=unit();grouped.update(id=13516,jp='AutomaticGroupSupportFixture')
        future=ability('47',[[0,3,3,[0,100,0,0,2,1,0]],[2,2,3,[100,0,0,0,2,1,0]],
            [2,1,24,[50,0,0,0,2,1]]],name='Independent group support',cost={'MP':0},attack_frames=[[90]],attack_damage=[[100]])
        parents=[ability('48',[[0,3,103,[47,0,0]]],'passive',cost={}),
            ability('49',[[0,3,66,[47,65,0]]],'passive',cost={}),
            ability('50',[[0,3,104,[47,0,0]]],'passive',cost={})]
        delayed_parent=ability('51',[[0,3,132,[47,0,3,100,0]]],attack_frames=[[24]],attack_damage=[[100]])
        with SourceCatalog() as catalog:
            for record in [*parents,delayed_parent,future]:catalog.add(record)
            catalog.finish()
            with patch.object(StudioResolver,'resolve',side_effect=catalog.resolve):
                autoport.autoport(grouped,{}, {'region':'GLW','abilities':[entry(delayed_parent)],'passives':[entry(p) for p in parents]})
        cls.grouped_passives=list(grouped['convertedPassives'].values())
        cls.grouped_command=next(iter(grouped['skills'].values()))
        generator.prepare_converted_passives(grouped,tbl)
        for sid,spec in grouped['skills'].items():
            with patch.object(generator,'command_motion_seconds',return_value=2.):
                generator.prepare_converted_command(grouped,spec,int(sid),tbl,clones,jobs)
        out = cls.work/"assets"
        path = cls.work/"patch.json"
        path.write_text(json.dumps({"legacyRoot":generator.LEGACY,"outRoot":str(out),
            "tables":list(tables.values()),"clones":clones}),encoding="utf8")
        cls.run_dt([*generator.FFRDT,"patch",str(path),"--usmap",generator.USMAP])
        cls.assets = []
        for index,job in enumerate(jobs):
            work = cls.work/str(index); work.mkdir()
            sequence.build(job,out,work,generator.FFRDT,generator.USMAP,cls.run_dt)
            cls.assets.append((cls.dump(out/(job["asset"]+".uasset"),"tojson"),
                               cls.dump(out/(job["asset"]+".uasset"),"seqdump"),job["plan"]))
        cls.skills = cls.dump(out/(generator.DT+"Skill/DT_SkillData.uasset"),"rows")["rows"]
        cls.passives = cls.dump(out/(generator.DT+"Skill/DT_PassiveSkillData.uasset"),"rows")["rows"]
        cls.effects = cls.dump(out/(generator.DT+"Skill/DT_SkillEffectData.uasset"),"rows")["rows"]
        cls.general = cls.dump(out/(generator.DT+"Skill/Other/DT_SkillGeneralData.uasset"),"rows")["rows"]["NewRow"]

    def test_automatic_children_cook_independent_self_ally_and_enemy_bundles(self):
        effects={e['ID']:e for e in self.effects.values()};skills={s['ID']:s for s in self.skills.values()}
        self.assertEqual(len(self.grouped_passives),3)
        parents=[*[self.passives[p['jp']] for p in self.grouped_passives],self.skills[self.grouped_command['jp']]]
        triggers=[]
        for parent in parents:
            grant=effects[next(b['effectId'] for b in parent['effectBundleList'] if b['effectId']>=0)]
            triggers.append(grant['applyTiming']);private=skills[grant['ParamList'][1]]
            self.assertEqual([(b['TargetType'],b['targetRelation']) for b in private['effectBundleList']],
                [('Self','Friendlies'),('Group','Friendlies'),('Group','Enemies')])
            self.assertEqual((private['TargetType'],private['Cost'],private['magnification']),('Self',0,0))
            self.assertEqual(private['playSequencerId'],-1);self.assertEqual(private['belongCommandList'],[])
            self.assertTrue(private['isAliveOnly'] and private['isParallelExecutable'])
            self.assertIn(private['ID'],self.general['equipperActionVisionSkills'])
        self.assertEqual(triggers,['AddEffect','BeginTurn','Revival','BeginTurn'])

    def test_battle_start_passive_cooks_all_fifteen_bundles_and_private_child(self):
        parent=self.passives[self.startup_spec['jp']];bundles=parent['effectBundleList']
        self.assertEqual(len(bundles),15)
        self.assertEqual([b['passiveSkillAddTiming'] for b in bundles],['SpawnUnit']*14+['BeginBattle'])
        effects={e['ID']:e for e in self.effects.values()};skills={s['ID']:s for s in self.skills.values()}
        grant=effects[bundles[-1]['effectId']];private=skills[grant['ParamList'][1]]
        self.assertEqual((grant['applyTiming'],grant['proceedTiming'],grant['effectEndActionNum']),('AddEffect','AddEffect',1))
        self.assertEqual(grant['ParamList'][4],1);self.assertEqual(private['Cost'],0)
        self.assertTrue(private['isAliveOnly']);self.assertEqual(private['belongCommandList'],[])
        self.assertIn(private['ID'],self.general['equipperActionVisionSkills'])

    def test_automatic_passives_cook_private_active_children_and_both_triggers(self):
        effects={e['ID']:e for e in self.effects.values()};skills={s['ID']:s for s in self.skills.values()}
        triggers=set()
        self.assertEqual(len(self.automatic_specs),2)
        for spec in self.automatic_specs:
            parent=self.passives[spec['jp']];bundle=parent['effectBundleList'][0]
            self.assertEqual(bundle['passiveSkillAddTiming'],'SpawnUnit')
            grant=effects[bundle['effectId']];private=skills[grant['ParamList'][1]]
            triggers.add(grant['applyTiming'])
            self.assertEqual((grant['effectEndActionNum'],grant['proceedTiming']),(-1,'None'))
            self.assertTrue(grant['isUnremovable']);self.assertEqual(grant['ParamList'][4],0)
            self.assertEqual(private['Cost'],0);self.assertEqual(private['belongCommandList'],[])
            self.assertTrue(private['isAliveOnly']);self.assertTrue(private['isParallelExecutable'])
            self.assertIn(private['ID'],self.general['equipperActionVisionSkills'])
            support=effects[private['effectBundleList'][0]['effectId']]
            self.assertEqual(support['EffectType'],'ParameterContinuousVariation')
        self.assertEqual(triggers,{'BeginTurn','Revival'})

    def test_delayed_command_cooks_one_private_future_support(self):
        root=self.skills[self.delayed_spec['jp']];effects={e['ID']:e for e in self.effects.values()};skills={s['ID']:s for s in self.skills.values()}
        grant=effects[root['effectBundleList'][0]['effectId']];private=skills[grant['ParamList'][1]]
        self.assertEqual((grant['applyTiming'],grant['proceedTiming'],grant['effectEndActionNum']),('BeginTurn','BeginTurn',3))
        self.assertEqual(grant['activationProbability'],65)
        self.assertEqual((private['Cost'],private['magnification'],private['playSequencerId']),(0,0,-1))
        self.assertEqual(private['belongCommandList'],[]);self.assertTrue(private['isParallelExecutable'])
        self.assertFalse(private['isAvailableWhenDead']);self.assertTrue(private['isAliveOnly'])
        self.assertEqual([effects[b['effectId']]['ParamList'][:3] for b in private['effectBundleList']],[[20,5,2]])
        self.assertIn(private['ID'],self.general['equipperActionVisionSkills'])

    def test_commands_use_own_power_cost_targets_and_selection(self):
        rows = [self.skills[s["jp"]] for s in self.unit["skills"].values()]
        self.assertEqual(rows[0]["DamageType"],"Magic")
        self.assertEqual(rows[0]["Cost"],0)  # Explicit Studio cost overrides survive the build.
        self.assertEqual(rows[0]["hitDamageRatioList"][:2],[.25,.75])
        self.assertLess(rows[0]["magnification"],201)
        support = next(r for r in rows if r["DamageType"] == "None")
        self.assertEqual(support["magnification"],0)
        for row in rows:
            self.assertEqual(row["belongCommandList"],[999])
            self.assertEqual(row["playSequencerId"],row["ID"]+1)
            self.assertNotIn(row["ID"],self.general['equipperActionVisionSkills'])
            self.assertEqual(row['mimicableUnitId'],self.unit['id'])
        self.assertIn({"SkillId":support["ID"],"costType":"LB","Cost":100},self.general["additionalCostData"])
        self.assertIn({"SkillId":support["ID"],"costType":"LB","Cost":100},self.general["costCheckData"])

    def test_attack_and_party_recovery_cook_with_independent_recipients_and_budgets(self):
        root=self.skills[self.mixed_recovery_spec['jp']]
        bundles=[b for b in root['effectBundleList'] if b['effectId']>=0]
        effects={e['ID']:e for e in self.effects.values()}
        by_id={r['ID']:r for r in self.skills.values()}
        rows=[root,*[by_id[effects[b['effectId']]['ParamList'][0]] for b in bundles]]
        self.assertEqual([(b['TargetType'],b['targetRelation']) for b in bundles],
                         [('Group','Friendlies'),('SkillTarget','Enemies'),('Group','Enemies')])
        self.assertEqual([r['parameterVariationType'] for r in rows],['Decrease','Increase','Decrease','Decrease'])
        self.assertEqual(rows[1]['magnification'],50)
        self.assertEqual(rows[1]['hitDamageRatioList'][:4],[0.,1.,0.,0.])
        self.assertAlmostEqual(sum(sum(r['hitDamageRatioList']) for r in rows if r['parameterVariationType']=='Decrease'),1.)
        self.assertEqual([r['Cost'] for r in rows],[18,0,0,0])
        self.assertTrue(all(r['ID'] not in self.general['equipperActionVisionSkills'] for r in rows[1:]))
        plan=next(plan for _,_,plan in self.assets if any(e['set'].get('Other_Reaction_Id')==root['ID'] for e in plan['events']))
        self.assertEqual([e['time'] for e in plan['events'] if e['set']['EventType']=='OtherReaction'],
                         [12000+f*400 for f in (12,18,24,30)])

    def test_random_ailments_cook_as_choices_with_one_command_event(self):
        effects={e['ID']:e for e in self.effects.values()}
        for index,spec in enumerate(self.random_specs[:2]):
            row=self.skills[spec['jp']]
            self.assertEqual((row['Cost'],row['DamageType'],row['magnification']),(18,'None',0))
            bundles=[b for b in row['effectBundleList'] if b['effectId']>=0]
            self.assertEqual(len(bundles),1)
            root=effects[bundles[0]['effectId']]
            self.assertEqual(root['EffectType'],'AddRandEffect')
            def walk(effect):
                if effect['EffectType'] in ('AddRandEffect','AddEffect'):
                    limit=5 if effect['EffectType']=='AddRandEffect' else 4
                    ids=[x for x in effect['ParamList'][1:] if x!=-1]
                    self.assertTrue(1<=len(ids)<=limit)
                    return [s for eid in ids for s in walk(effects[eid])]
                return [effect['statusCondition']]
            self.assertEqual(walk(root),['Poison'] if index==0 else
                ['Poison','Blind','Sleep','Silence','Paralyzation','Confusion','AttackDown','IntelligenceDown','Stoned'])
            plan=next(plan for _,_,plan in self.assets if any(e['set'].get('Other_Reaction_Id')==row['ID'] for e in plan['events']))
            self.assertEqual([e['time'] for e in plan['events'] if e['set']['EventType']=='OtherReaction'],[24000+24*400])

    def test_partial_ordered_ailments_cook_the_capped_probability_graph(self):
        from collections import Counter
        from fractions import Fraction
        from functools import lru_cache
        effects={e['ID']:e for e in self.effects.values()}
        row=self.skills[self.random_specs[2]['jp']]
        @lru_cache(None)
        def walk(eid):
            effect=effects[eid];kind=effect['EffectType']
            if kind=='AddRandEffect':
                children=[v for v in effect['ParamList'][1:6] if v!=-1]
                result=Counter()
                if not children:result[()]=Fraction(1)
                for child in children:
                    for outcome,p in walk(child).items():result[outcome]+=p/len(children)
                return result
            if kind=='AddEffect':
                result={():Fraction(1)}
                for child in (v for v in effect['ParamList'][1:5] if v!=-1):
                    result={a+b:pa*pb for a,pa in result.items() for b,pb in walk(child).items()}
                return result
            self.assertEqual(effect['addProbability'],100)
            return {(effect['statusCondition'],):Fraction(1)}
        outcomes=walk(row['effectBundleList'][0]['effectId'])
        self.assertEqual(sum(outcomes.values()),1)
        self.assertEqual(outcomes[()],Fraction(1,256))
        self.assertEqual(outcomes[('Poison','Blind','Sleep')],Fraction(1,8))
        self.assertTrue(all(len([s for s in outcome if s!='IntelligenceDown'])<=3 for outcome in outcomes))
        self.assertEqual((row['Cost'],row['DamageType'],row['magnification']),(18,'None',0))
        plan=next(plan for _,_,plan in self.assets if any(e['set'].get('Other_Reaction_Id')==row['ID'] for e in plan['events']))
        self.assertEqual([e['time'] for e in plan['events'] if e['set']['EventType']=='OtherReaction'],[33600])

    def test_stop_cooks_its_own_status_with_native_incapacitation(self):
        root=self.skills[self.stop_spec['jp']]
        effect=next(e for e in self.effects.values() if e['ID']==root['effectBundleList'][0]['effectId'])
        self.assertEqual((root['TargetType'],root['DamageType'],root['magnification']),('Group','None',0))
        self.assertEqual((effect['EffectType'],effect['statusCondition'],effect['addProbability']),('AutomaticSkill','Stop',80))
        self.assertEqual((effect['applyTiming'],effect['proceedTiming'],effect['effectEndActionNum']),('ActionBegin','BeginTurn',3))
        self.assertEqual(effect['ParamList'][:8],[3,-1,-1,2000,0,1,0,0])

    def test_all_side_commands_cook_both_side_flags_and_selected_effect_bundles(self):
        damage,support=[self.skills[s['jp']] for s in self.all_specs]
        for row in (damage,support):
            self.assertEqual(row['TargetType'],'All');self.assertTrue(row['isAliveOnly'])
            self.assertFalse(row['isSameRelationTargetingDisabled']);self.assertFalse(row['isHostilityRelationTargetingDisabled'])
        self.assertEqual((damage['element'],damage['DamageType']),('Dark','Magic'))
        self.assertEqual(damage['hitDamageRatioList'][:2],[.3,.7])
        self.assertEqual([b['TargetType'] for b in support['effectBundleList'] if b['effectId']>=0],['SkillTarget']*2)

    def test_multiple_elements_cook_with_final_command_id_filter(self):
        root=self.skills[self.elemental_spec['jp']]
        bundle=next(b for b in root['effectBundleList'] if b['effectId']>=0)
        effect=next(e for e in self.effects.values() if e['ID']==bundle['effectId'])
        self.assertEqual((root['element'],root['hitCount']),('Fire',2))
        self.assertEqual(root['hitDamageRatioList'][:2],[.3,.7])
        self.assertEqual(effect['ParamList'][:2],[2,root['ID']])
        self.assertEqual((bundle['TargetType'],bundle['activeSkillAddTiming']),('Self','BeforeDamageCalculation'))
        self.assertEqual((effect['proceedTiming'],effect['effectEndActionNum']),('SkillEnd',1))

    def test_appended_elements_cook_private_ids_and_global_imbues_keep_their_chances(self):
        root,imbue=[self.skills[s['jp']] for s in self.combined_element_specs]
        effects={e['ID']:e for e in self.effects.values()};skills={s['ID']:s for s in self.skills.values()}
        fx=[effects[b['effectId']] for b in root['effectBundleList'] if b['effectId']>=0]
        child_ids=[e['ParamList'][0] for e in fx if e['EffectType']=='AppendDamage']
        self.assertEqual([e['ParamList'][:2] for e in fx if e['EffectType']=='AddElement'],
                         [[2,sid] for sid in [root['ID'],*child_ids]])
        rows=[root,*[skills[sid] for sid in child_ids]]
        self.assertEqual([r['DamageType'] for r in rows],['Physic','Magic','Physic','Magic'])
        self.assertAlmostEqual(sum(sum(r['hitDamageRatioList']) for r in rows),1.)
        self.assertTrue(all(r['Cost']==0 and not r['belongCommandList'] and r['playSequencerId']==-1 for r in rows[1:]))
        buffs=[effects[b['effectId']] for b in imbue['effectBundleList'] if b['effectId']>=0]
        self.assertEqual([e['ParamList'][:2] for e in buffs],[[1,-1],[2,-1],[6,-1]])
        self.assertEqual([e['addProbability'] for e in buffs],[100,50,75])
        self.assertTrue(all(e['proceedTiming']=='BeginTurn' and e['effectEndActionNum']==3 for e in buffs))

    def test_tag_stagger_cooks_exact_root_and_child_ids_in_nine_id_groups(self):
        effects={e['ID']:e for e in self.effects.values()};skills={s['ID']:s for s in self.skills.values()}
        for index,spec in enumerate(self.tag_specs):
            root=self.skills[spec['jp']]
            fx=[effects[b['effectId']] for b in root['effectBundleList'] if b['effectId']>=0]
            ids=[root['ID'],*[e['ParamList'][0] for e in fx if e['EffectType']=='AppendDamage']]
            buffs=[e for e in fx if e['EffectType']=='MulBaseBreakBySkill']
            self.assertEqual([v for e in buffs for v in e['ParamList'][1:10] if v!=-1],ids)
            self.assertTrue(all(e['ParamList'][0]==10 and e['ParamList'][10:]==[-1]*5 for e in buffs))
            self.assertTrue(all(e['proceedTiming']=='SkillEnd' and e['effectEndActionNum']==1 and e['isUnremovable'] for e in buffs))
            self.assertAlmostEqual(sum(sum(skills[sid]['hitDamageRatioList']) for sid in ids),1.)
            if index:
                self.assertEqual(len(ids),19);self.assertEqual(len(buffs),3)
                self.assertTrue(all(not skills[sid]['belongCommandList'] and skills[sid]['Cost']==0 for sid in ids[1:]))
            else:
                self.assertEqual([e['ParamList'][1] for e in fx if e['EffectType']=='AddElement'],[root['ID']])
                self.assertEqual(root['hitDamageRatioList'][:2],[.3,.7])

    def test_reraise_cooks_a_private_dead_actor_action_and_exact_cleanup(self):
        effects={e['ID']:e for e in self.effects.values()};skills={r['ID']:r for r in self.skills.values()}
        root=self.skills[self.reraise_spec['jp']]
        grant=effects[root['effectBundleList'][0]['effectId']];child=skills[grant['ParamList'][1]]
        revive,cleanup=[effects[b['effectId']] for b in child['effectBundleList'][:2]]
        self.assertEqual((grant['applyTiming'],grant['proceedTiming'],grant['effectEndActionNum']),('Reraise','BeginTurn',3))
        self.assertEqual(revive['ParamList'][0],80);self.assertEqual(cleanup['ParamList'][0],grant['ID'])
        self.assertEqual(cleanup['ParamList'][10],1)
        self.assertEqual((child['Cost'],child['belongCommandList'],child['playSequencerId']),(0,[],-1))
        self.assertTrue(child['isAvailableWhenDead']);self.assertNotIn(child['ID'],self.general['equipperActionVisionSkills'])
        plan=next(plan for _,_,plan in self.assets if any(e['set'].get('Other_Reaction_Id')==root['ID'] for e in plan['events']))
        self.assertEqual([e['time'] for e in plan['events'] if e['set']['EventType']=='OtherReaction'],[24000+24*400])

    def test_dispel_modes_cook_separately_under_one_command_event(self):
        effects={e['ID']:e for e in self.effects.values()}
        expected=[[[0,1],[0,0]],[[0,1]],[[0,0]]]
        for index,spec in enumerate(self.dispel_specs):
            root=self.skills[spec['jp']];rows=[effects[b['effectId']] for b in root['effectBundleList'] if b['effectId']>=0]
            self.assertEqual([r['ParamList'][:2] for r in rows],expected[index])
            self.assertTrue(all(r['EffectType']=='CureStatusCondition' and r['effectEndActionNum']==1 for r in rows))
            self.assertEqual(rows[-1]['ParamList'][10],1 if index!=1 else -1)
            self.assertEqual((root['magnification'],root['Cost']),(0,18))
            plan=next(plan for _,_,plan in self.assets if any(e['set'].get('Other_Reaction_Id')==root['ID'] for e in plan['events']))
            self.assertEqual([e['time'] for e in plan['events'] if e['set']['EventType']=='OtherReaction'],[24000+24*400])

    def test_mixed_damage_and_buff_cook_with_native_phase_binding(self):
        spec = next(s for s in self.unit["skills"].values() if s["ffbe"]["id"] == 5)
        row = self.skills[spec["jp"]]
        self.assertEqual(row["hitCount"],2)
        bundle = row["effectBundleList"][0]
        self.assertEqual(bundle["activeSkillAddTiming"],"AfterDamageCalculation")
        self.assertEqual((bundle["TargetType"],bundle["targetRelation"]),("Self","Friendlies"))
        effect = next(e for e in self.effects.values() if e["ID"] == bundle["effectId"])
        self.assertEqual(effect["ParamList"][:3],[20,5,2])

    def test_partial_timing_cooks_correct_hits_weights_and_support_phases(self):
        spec=next(s for s in self.unit["skills"].values() if s["ffbe"]["id"]==22)
        row=self.skills[spec["jp"]]
        self.assertEqual(row["hitCount"],2)
        self.assertAlmostEqual(row["hitDamageRatioList"][0],.2)
        self.assertAlmostEqual(row["hitDamageRatioList"][1],.8)
        bundles=[b for b in row["effectBundleList"] if b["effectId"]>=0]
        self.assertEqual(len(bundles),2)
        self.assertTrue(all(b["activeSkillAddTiming"]=="AfterDamageCalculation" for b in bundles))
        plan=next(plan for _,_,plan in self.assets if any(e["set"].get("Other_Reaction_Id")==row["ID"] for e in plan["events"]))
        self.assertEqual([e["time"] for e in plan["events"] if e["set"]["EventType"]=="OtherReaction"],
                         [12000+16*400,12000+58*400])

    def test_extended_command_cooks_all_fifty_two_hits_and_weight_slots(self):
        row=self.skills[self.extended_spec["jp"]]
        self.assertEqual(row["hitCount"],52)
        self.assertEqual(len(row["hitDamageRatioList"]),52)
        self.assertAlmostEqual(sum(row["hitDamageRatioList"]),1.,places=6)
        self.assertAlmostEqual(row["hitDamageRatioList"][-1],53/104,places=6)
        plan=next(plan for _,_,plan in self.assets if any(e["set"].get("Other_Reaction_Id")==row["ID"] for e in plan["events"]))
        self.assertEqual([e["time"] for e in plan["events"] if e["set"]["EventType"]=="OtherReaction"],
                         [24000+(12+i*4)*400 for i in range(52)])

    def test_recovery_cooks_one_budget_and_cures_in_both_native_phases(self):
        row=self.skills[self.recovery_spec["jp"]]
        self.assertEqual((row["parameterVariationType"],row["skillEffectType"],row["hitCount"]),
                         ("Increase","DamageAndRecovery",1))
        self.assertEqual(row["magnification"],330)
        self.assertEqual((row["Cost"],row["TargetType"],row["defaultTargetRelation"]),(18,"Group","Friendlies"))
        bundles=[b for b in row["effectBundleList"] if b["effectId"]>=0]
        self.assertEqual([b["activeSkillAddTiming"] for b in bundles],["BeforeDamageCalculation","AfterDamageCalculation"])
        effects=[next(e for e in self.effects.values() if e["ID"]==b["effectId"]) for b in bundles]
        self.assertEqual([e["EffectType"] for e in effects],["CureStatusCondition"]*2)
        self.assertEqual([e["ParamList"][3] for e in effects],[9,18])
        plan=next(plan for _,_,plan in self.assets if any(e["set"].get("Other_Reaction_Id")==row["ID"] for e in plan["events"]))
        self.assertEqual([e["time"] for e in plan["events"] if e["set"]["EventType"]=="OtherReaction"],[24000+160*400])

    def test_composite_command_cooks_thirty_two_private_applications(self):
        row=self.skills[self.composite_spec["jp"]]
        bundles=[b for b in row["effectBundleList"] if b["effectId"]>=0]
        self.assertEqual(len(bundles),31)
        rows=[row]
        for bundle in bundles:
            effect=next(e for e in self.effects.values() if e["ID"]==bundle["effectId"])
            self.assertEqual(effect["EffectType"],"AppendDamage")
            self.assertEqual(effect["ParamList"][1],0)
            self.assertEqual(bundle["TargetType"],"SkillTarget")
            self.assertEqual(bundle["activeSkillAddTiming"],"AfterDamageCalculation")
            child=next(r for r in self.skills.values() if r["ID"]==effect["ParamList"][0])
            rows.append(child)
            self.assertEqual((child["Cost"],child["belongCommandList"],child["playSequencerId"]),(0,[],-1))
            self.assertNotIn(child["ID"],self.general["equipperActionVisionSkills"])
        for i,r in enumerate(rows):
            self.assertEqual((r["hitCount"],r["DamageType"]),(1,"Magic" if i%2 else "Physic"))
            self.assertAlmostEqual(r["hitDamageRatioList"][i],1/24 if i%2 else 1/48)
            self.assertAlmostEqual(sum(r["hitDamageRatioList"]),r["hitDamageRatioList"][i])
        self.assertAlmostEqual(sum(sum(r["hitDamageRatioList"]) for r in rows),1.)
        plan=next(plan for _,_,plan in self.assets if any(e["set"].get("Other_Reaction_Id")==row["ID"] for e in plan["events"]))
        self.assertEqual([e["time"] for e in plan["events"] if e["set"]["EventType"]=="OtherReaction"],
                         [12000+f*400 for f in range(12,76,2)])

    def test_passive_grant_has_its_actual_stone_killer_substitute(self):
        spec = self.unit["convertedPassives"]["50000"]
        row = self.passives[spec["jp"]]
        eid = row["effectBundleList"][0]["effectId"]
        effect = next(e for e in self.effects.values() if e["ID"] == eid)
        self.assertEqual(effect["EffectType"],"ParameterContinuousVariation")
        self.assertEqual(effect["ParamList"][:3],[20,6,2])

    def test_scalar_killer_passives_cook_with_shared_budgets_and_awakening_grants(self):
        by_id={e["ID"]:e for e in self.effects.values()}
        def effects(effect_id):
            effect=by_id[effect_id]
            if effect["EffectType"]=="AddEffect":
                return [child for eid in effect["ParamList"][1:5] if eid>=0 for child in effects(eid)]
            return [effect]
        for destination,expected in ((50001,[(5,3),(6,3),(7,2),(8,2)]),(50002,[(5,1),(6,1)])):
            with self.subTest(destination=destination):
                spec=self.unit["convertedPassives"][str(destination)]
                row=self.passives[spec["jp"]]
                bundles=[b for b in row["effectBundleList"] if b["effectId"]>=0]
                actual=[effect for b in bundles for effect in effects(b["effectId"])]
                self.assertEqual([(e["ParamList"][1],e["ParamList"][0]) for e in actual],expected)
                self.assertTrue(all(e["EffectType"]=="ParameterContinuousVariation" for e in actual))
                self.assertTrue(all(e["effectEndActionNum"]==-1 and e["proceedTiming"]=="None" for e in actual))
                self.assertTrue(all(b["TargetType"]=="Self" and b["passiveSkillAddTiming"]=="SpawnUnit" for b in bundles))
                grants=[grant for tier in self.unit["awakening"] for grant in tier]
                self.assertEqual(grants.count(["PassiveSkill",destination]),1)
                self.assertTrue(all(len(tier)<=8 for tier in self.unit["awakening"]))

    def test_rate_passives_cook_with_correct_types_percentages_and_grants(self):
        cases=(("Preemtive",[1,0]),("EncountRatio",[70]),("ExperienceUp",[120]),("MoneyUp",[200]),
               ("ItemDropUp",[25]),("StealRate",[50]),("EncountRatio",[125]),("EncountRatio",[0]))
        by_id={e["ID"]:e for e in self.effects.values()}
        grants=[grant for tier in self.unit["awakening"] for grant in tier]
        for offset,(kind,parameters) in enumerate(cases,3):
            with self.subTest(kind=kind,parameters=parameters):
                destination=50000+offset
                spec=self.unit["convertedPassives"][str(destination)]
                row=self.passives[spec["jp"]]
                bundles=[b for b in row["effectBundleList"] if b["effectId"]>=0]
                self.assertEqual(len(bundles),1)
                effect=by_id[bundles[0]["effectId"]]
                self.assertEqual((effect["EffectType"],effect["ParamList"][:len(parameters)]),(kind,parameters))
                self.assertEqual((effect["effectEndActionNum"],effect["proceedTiming"]),(-1,"None"))
                self.assertEqual((bundles[0]["TargetType"],bundles[0]["passiveSkillAddTiming"]),("Self","SpawnUnit"))
                self.assertEqual(grants.count(["PassiveSkill",destination]),1)

    def test_mirage_and_caster_excluding_support_survive_the_actual_unit_builder(self):
        mirage = next(s for s in self.unit["skills"].values() if s["ffbe"]["id"] == 6)
        row = self.skills[mirage["jp"]]
        self.assertEqual((row["DamageType"],row["magnification"]),("None",0))
        effect_id=row["effectBundleList"][0]["effectId"]
        effect=next(e for e in self.effects.values() if e["ID"]==effect_id)
        self.assertEqual((effect["EffectType"],effect["ParamList"][:2]),("Avoidance",[20,1]))
        self.assertEqual((effect["proceedTiming"],effect["effectEndActionNum"]),("BeginTurn",4))
        filtered = next(s for s in self.unit["skills"].values() if s["ffbe"]["id"] == 7)
        row=self.skills[filtered["jp"]]
        self.assertTrue(row["isTargetIgnoreSelf"])
        self.assertEqual((row["TargetType"],row["effectBundleList"][0]["TargetType"]),("Group","SkillTarget"))
        self.assertIn("all other allies",filtered["desc"])

    def test_cooked_schedule_matches_source_times_without_resonance_events(self):
        sequence_tests.CookedResonanceTests.test_cooked_schedule_matches_channel(self)
        for _,_,plan in self.assets:
            events = [e["set"] for e in plan["events"]]
            self.assertFalse(any(e["EventType"].startswith("Post") for e in events))
            self.assertFalse(any(e.get("Unit_PlayAnimByName_AnimationName","").startswith("LB") for e in events))
        self.assertEqual([e["time"] for e in self.assets[0][2]["events"] if e["set"]["EventType"] == "OtherReaction"],
                         [24000+12*400,24000+36*400])

    def test_cooked_animation_events_target_visions_and_healing_has_no_hit_feedback(self):
        for asset,functions,plan in self.assets:
            fns = {int(k.split(':')[0]):v for k,v in functions.items()}
            actual = []
            for export in asset['Exports']:
                for prop in export.get('Data',[]):
                    if prop['Name'] != 'EventChannel': continue
                    actual.extend(fns[sequence.child(value['Value'],'Ptrs','Function')]
                                  for value in sequence.child(prop['Value'],'KeyValues'))
            motions = [e for e in actual if e['EventType'] == 'UnitPlayAnimByName']
            self.assertTrue(all(e.get('Unit_PlayAnimByName_IsOnlyVisionUnit') for e in motions))
            self.assertTrue(all(not e.get('Unit_PlayAnimByName_SkipDualcast') for e in motions))
            names = [e['Unit_PlayAnimByName_AnimationName'] for e in motions]
            if 'magic_attack' in names:
                self.assertLess(names.index('magic_idle'),names.index('magic_attack'))
            reaction = next(e for e in actual if e['EventType'] == 'OtherReaction')
            row = next(r for r in self.skills.values() if r['ID'] == reaction['Other_Reaction_Id'])
            if row['parameterVariationType'] == 'Increase' and row['skillEffectType'] == 'DamageAndRecovery':
                self.assertFalse(reaction.get('Otber_Reaction_bReturnIdleMotion'))
                if row['parameterType'] == 'HitPoint':
                    self.assertTrue(any(e['EventType'] == 'EffectSpawnNiagaraAtTarget' and
                        e.get('Effect_SpawnTarget_bAllTarget') and
                        'NS_EF_SKL210030_Root' in str(e.get('Effect_SpawnTarget_NiagaraData')) for e in actual))

    def test_cover_wards_cook_with_protected_recipients_and_damage_filters(self):
        for source_id,shape,params,turns in ((8,"Group",[[2,18]],3),(9,"Single",[[1,20],[2,20]],2)):
            with self.subTest(source_id=source_id):
                spec=next(s for s in self.unit["skills"].values() if s["ffbe"]["id"]==source_id)
                row=self.skills[spec["jp"]]
                self.assertEqual((row["TargetType"],row["isTargetIgnoreSelf"]),(shape,True))
                self.assertEqual((row["DamageType"],row["magnification"]),("None",0))
                bundles=[b for b in row["effectBundleList"] if b["effectId"]>=0]
                self.assertTrue(all(b["TargetType"]=="SkillTarget" for b in bundles))
                effects=[next(e for e in self.effects.values() if e["ID"]==b["effectId"]) for b in bundles]
                self.assertEqual([e["ParamList"][:2] for e in effects],params)
                self.assertTrue(all(e["EffectType"]=="Deffence" and e["effectEndActionNum"]==turns for e in effects))
                self.assertTrue(all(not e["isUnremovable"] for e in effects))

    def test_race_attacks_cook_base_damage_and_a_separate_caster_reward(self):
        for source_id,damage,params in ((10,"Physic",[20,6,2]),(11,"Magic",[8,8,2])):
            with self.subTest(source_id=source_id):
                spec=next(s for s in self.unit["skills"].values() if s["ffbe"]["id"]==source_id)
                row=self.skills[spec["jp"]]
                self.assertEqual((row["DamageType"],row["defaultTargetRelation"]),(damage,"Enemies"))
                self.assertEqual(row["magnification"],commands.converter().native.power(1,damage))
                self.assertEqual(row["hitDamageRatioList"][:2],[.25,.75])
                bundle=row["effectBundleList"][0]
                self.assertEqual((bundle["TargetType"],bundle["targetRelation"]),("Self","Friendlies"))
                self.assertEqual(bundle["activeSkillAddTiming"],"AfterDamageCalculation")
                effect=next(e for e in self.effects.values() if e["ID"]==bundle["effectId"])
                self.assertEqual(effect["ParamList"][:3],params)
                self.assertEqual((effect["EffectType"],effect["effectEndActionNum"]),("ParameterContinuousVariation",1))


if __name__ == "__main__":
    unittest.main()
