"""Semantic and native serialization regressions for structured conversion."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
from ability_converter import Converter, SourceRecord
from ability_converter.compiler import TableWriter
from ability_converter.graph import SkillGraph
from ability_converter.catalog import SourceCatalog
from ability_converter.sources import master_record, structured_records


def source(raw_effects, kind="ability", sid="fixture", **extra):
    data = {"name":"Fixture", "effects_raw":raw_effects, "mp_cost":10,
            "attack_frames":[[12,24]], "attack_damage":[[30,70]], **extra}
    return SourceRecord("TEST",kind,sid,data)


class ConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = Converter()

    def test_damage_and_self_buff_keep_targets_and_order(self):
        r = self.c.convert(source([[0,3,3,[100,0,0,0,3,1]], [2,1,1,[0,0,0,0,0,0,500,0]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        row = r["native"]
        self.assertEqual(row["set"]["defaultTargetRelation"],"Enemies")
        self.assertEqual(row["effects"][0]["target"]["shape"],"Self")
        self.assertEqual(row["effects"][0]["activeTiming"],"BeforeDamageCalculation")
        self.assertEqual(row["sequence"]["hitFrames"],[12,24])
        self.assertEqual(row["set"]["hitDamageRatioList"][:2],[.3,.7])

    def test_agnes_support_is_not_damage(self):
        r = self.c.convert(source([[2,1,33,[0,0,0,0,0,0,-50,0,1,3]],
            [2,2,3,[0,100,0,100,3,1]], [2,2,111,[0,0,0,0,1,0]]],kind="lb",lb_cost=20))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["set"]["magnification"],0)
        self.assertEqual(r["native"]["set"]["DamageType"],"None")
        effects = r["native"]["effects"]
        self.assertEqual([e["target"]["relation"] for e in effects],["Enemies","Friendlies","Friendlies","Friendlies"])
        self.assertEqual(effects[-1]["set"]["EffectType"],"CureStatusCondition")
        self.assertEqual(effects[-1]["set"]["ParamList"][3],9)

    def test_damage_only_timing_groups_keep_both_portions_before_imperil(self):
        r = self.c.convert(source([[2,1,15,[0,0,0,0,0,200,0]], [2,1,15,[0,0,0,0,0,800,0]],
                                  [2,1,33,[0,0,0,-100,0,0,0,0,1,3]]],
                                 kind="magic", attack_frames=[[52,72,92,112],[132]],
                                 attack_damage=[[25,25,25,25],[100]], attack_count=[4,1]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["sequence"]["hitFrames"],[52,72,92,112,132])
        weights = r["native"]["set"]["hitDamageRatioList"][:5]
        for actual,expected in zip(weights,[.05,.05,.05,.05,.8]):
            self.assertAlmostEqual(actual,expected)
        self.assertEqual(r["native"]["effects"][0]["activeTiming"],"AfterDamageCalculation")

    def test_names_and_descriptions_do_not_classify_effects(self):
        a = source([[2,2,5,[8,0,0,0,0,0,0,0]]],name="Stone Killer",effects=["Inflict poison"])
        b = source(a.data["effects_raw"],name="回復",effects=["Nothing"])
        self.assertEqual(self.c.convert(a)["native"],self.c.convert(b)["native"])
        effect = self.c.convert(a)["native"]["effects"][0]["set"]
        self.assertEqual((effect["EffectType"],effect["ParamList"][3]),("CureStatusCondition",7))

    def test_partial_component_timing_keeps_damage_before_trailing_support(self):
        r=self.c.convert(source([[1,1,1,[0,0,0,0,0,0,250,0]], [0,3,3,[80,0,0,0,5,1]],
                                [0,3,95,[0,0,0,0,0,100,0,0,5,1]]],
                               attack_frames=[[16,58],[120]],attack_damage=[[50,50],[100]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["sequence"]["hitFrames"],[16,58])
        self.assertEqual(r["native"]["set"]["hitDamageRatioList"][:2],[.5,.5])
        self.assertEqual(r["native"]["sequence"]["components"][0]["timingBinding"],
                         {"layout":"component_prefix","groupIndex":0,"componentIndex":0,"groupCount":2})

    def test_partial_component_timing_keeps_damage_after_leading_effects(self):
        r=self.c.convert(source([[2,1,33,[-100,0,0,0,0,0,0,0,1,3]], [0,3,3,[60,0,0,0,3,1]],
                                [2,1,1,[0,0,0,0,0,0,1000]], [0,3,3,[0,60,0,0,3,1]]],
                               attack_frames=[[10],[20],[30,42]],attack_damage=[[100],[100],[25,75]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["sequence"]["hitFrames"],[30,42])
        self.assertEqual(r["native"]["set"]["hitDamageRatioList"][:2],[.25,.75])
        self.assertEqual(r["native"]["sequence"]["components"][0]["timingBinding"]["groupIndex"],2)

    def test_partial_recovery_timing_uses_source_frame_instead_of_zero(self):
        r=self.c.convert(source([[2,2,2,[0,0,3000,1800,100]], [2,2,8,[300,1,9000,3]],
                                [2,2,3,[0,200,0,0,3,1,0]]],
                               attack_frames=[[160],[160]],attack_damage=[[100],[100]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["sequence"]["hitFrames"],[160])
        self.assertEqual(r["native"]["set"]["parameterVariationType"],"Increase")
        self.assertEqual(r["native"]["set"]["hitDamageRatioList"][0],1.)
        self.assertEqual(r["native"]["sequence"]["components"][0]["timingBinding"]["layout"],"component_prefix")

    def test_weighted_recovery_hits_require_separate_budgets(self):
        for frames,weights in (([12,24],[30,70]),([12,24],[100,0])):
            r=self.c.convert(source([[2,2,2,[0,0,3000,1800,100]]],
                                    attack_frames=[frames],attack_damage=[weights]))
            self.assertFalse(r["validation"]["tableCompatible"])
            self.assertIn("Recovery bypasses native hit weights", " ".join(r["issues"]))

    def test_identical_timing_groups_can_be_shared_by_later_damage(self):
        r=self.c.convert(source([[0,3,3,[60,0,0,0,3,1]], [0,3,3,[0,60,0,0,3,1]],
                                [0,3,3,[0,0,60,0,3,1]], [2,1,1,[0,0,0,0,0,0,1000]]],
                               attack_frames=[[10,30]]*3,attack_damage=[[20,80]]*3))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["sequence"]["hitFrames"],[10,30])
        self.assertEqual(r["native"]["set"]["hitDamageRatioList"][:2],[.2,.8])
        self.assertEqual(r["native"]["sequence"]["components"][0]["timingBinding"]["layout"],"shared_identical")

    def test_out_of_range_different_or_empty_timing_stays_held(self):
        effects=[[0,3,3,[60,0,0,0,3,1]], [0,3,3,[0,60,0,0,3,1]], [2,1,1,[0,0,0,0,0,0,1000]]]
        for frames,weights in (([[10],[20]],[[100],[100]]), ([[10,20],[10,20]],[[20,80],[80,20]]),
                               ([[],[]],[[],[]]), ([[10],[]],[[100],[]])):
            with self.subTest(frames=frames,weights=weights):
                r=self.c.convert(source(effects,attack_frames=frames,attack_damage=weights))
                self.assertFalse(r["validation"]["tableCompatible"])
                self.assertIn("Missing or ambiguous hit frames"," ".join(r["issues"]))
        r=self.c.convert(source([effects[-1],*effects[:2]],attack_frames=[[],[10]],attack_damage=[[],[100]]))
        self.assertFalse(r["validation"]["tableCompatible"])

    def test_compact_timing_after_leading_support_keeps_each_damage_portion(self):
        r=self.c.convert(source([[1,1,33,[-120,0,0,0,0,0,0,0,1,3]],
                                [1,1,1,[0,0,0,0,0,0,3400,0]], [1,1,1,[0,0,0,0,0,0,3700,0]]],
                               attack_frames=[[70,76,82,88,94,100,106],[112]],
                               attack_damage=[[14,14,14,14,14,14,16],[100]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["sequence"]["hitFrames"],[70,76,82,88,94,100,106,112])
        self.assertAlmostEqual(r["native"]["set"]["hitDamageRatioList"][7],37/71)
        self.assertEqual([j["timingBinding"]["layout"] for j in r["native"]["sequence"]["components"]],["compact_actions"]*2)

    def test_inline_child_retains_partial_timing_binding_and_parent_cost(self):
        child=source([[2,1,1,[0,0,0,0,0,0,1000]], [0,3,3,[0,60,0,0,3,1]],
                      [0,3,3,[0,0,60,0,3,1]]],sid="200",mp_cost=99,
                     attack_frames=[[16,58],[120]],attack_damage=[[20,80],[100]])
        parent=source([[0,3,71,[200,1]]],sid="100",mp_cost=12,attack_frames=[[]],attack_damage=[[]])
        with SourceCatalog() as catalog:
            catalog.add(child); catalog.add(parent); catalog.finish()
            r=Converter(resolver=catalog).convert(parent)
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["set"]["Cost"],18)
        job=r["native"]["sequence"]["components"][0]
        self.assertEqual((job["source"],job["frames"],job["weights"]),(child.key,[16,58],[.2,.8]))
        self.assertEqual(job["timingBinding"]["layout"],"component_prefix")

    def test_namespaces_are_not_interchangeable(self):
        r = self.c.convert(source([[0,3,1,[100,0,0,0,0,0]]],kind="passive"))
        self.assertEqual(r["native"]["effects"][0]["set"]["EffectType"],"ParameterContinuousVariation")
        self.assertFalse(r["components"][0]["actions"])

    def test_hybrid_becomes_magic_once(self):
        r = self.c.convert(source([[2,1,40,[0,0,0,0,0,0,0,0,1000,1000]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["set"]["DamageType"],"Magic")
        self.assertEqual(r["components"][0]["actions"][0]["multiple"],10)
        self.assertEqual(r["status"],"replaced")

    def test_revive_targets_dead_without_reraise(self):
        r = self.c.convert(source([[1,2,4,[50]]]))
        self.assertEqual(r["native"]["set"]["defaultTargetState"],"Dead")
        self.assertEqual(r["native"]["effects"][0]["set"]["EffectType"],"Revival")

    def test_mirage_uses_bounded_timed_physical_evasion_replacement(self):
        for hits,expected in ((0,15),(1,15),(2,20),(3,25),(4,30),(99,30)):
            with self.subTest(hits=hits):
                r=self.c.convert(source([[2,2,54,[hits,7,0]]]))
                self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
                self.assertEqual(r["status"],"replaced")
                self.assertEqual(r["components"][0]["replacement"],"Mirage Veil")
                effect=r["native"]["effects"][0]["set"]
                self.assertEqual(effect["EffectType"],"Avoidance")
                self.assertEqual(effect["ParamList"][:2],[expected,1])
                self.assertEqual((effect["applyTiming"],effect["proceedTiming"],effect["effectEndActionNum"]),("None","BeginTurn",7))
                self.assertFalse(effect["isUnremovable"])
                self.assertIn(f"{expected}% physical evasion",TableWriter.description(r))
                self.assertEqual(r["native"]["set"]["magnification"],0)

    def test_reraise_records_native_cleanup_link_without_exporting_a_permanent_revive(self):
        r=self.c.convert(source([[2,2,27,[80,3,1]]]))
        self.assertEqual(r["status"],"blocked")
        semantic=r["components"][0]["semantic"]
        self.assertEqual((semantic["hpPercent"],semantic["turns"]),(80,3))
        candidate=semantic["nativeBinding"]
        self.assertEqual((candidate["reviveSkillId"],candidate["reviveEffectId"]),(210240,1026))
        self.assertEqual((candidate["cleanupEffectId"],candidate["grantEffectId"]),(20015,1077))
        self.assertEqual(semantic["sourceControlParameters"],[1])
        self.assertFalse(r["components"][0]["effects"])
        with self.assertRaises(ValueError): TableWriter(self.c.native).add(r)

    def test_mirage_unknown_controls_and_invalid_counts_remain_held(self):
        for params in ([1,3,1],[1,3,0,1],[-1,3],[1.5,3],[1,0],[1,3,True]):
            with self.subTest(params=params):
                r=self.c.convert(source([[0,3,54,params]]))
                self.assertEqual(r["status"],"blocked")
                self.assertFalse(r["components"][0]["effects"])
        r=self.c.convert(source([[0,3,54,[1,3]]]))
        self.assertEqual(r["status"],"replaced")

    def test_cover_ward_protects_other_allies_without_redirecting_damage(self):
        r=self.c.convert(source([[0,3,96,[1,0,50,70,80,100,3,1,1]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        c=r["components"][0]
        self.assertEqual(c["replacement"],"Guardian Ward")
        self.assertEqual(c["semantic"]["protector"]["shape"],"Self")
        self.assertEqual(c["semantic"]["protected"]["selection"],"all_other_allies_of_protector")
        self.assertEqual(c["semantic"]["mitigationRange"],[50,70])
        effect=r["native"]["effects"][0]
        self.assertEqual(effect["set"]["EffectType"],"Deffence")
        self.assertEqual(effect["set"]["ParamList"][:4],[1,18,0,0])
        self.assertEqual((effect["set"]["proceedTiming"],effect["set"]["effectEndActionNum"]),("BeginTurn",3))
        self.assertFalse(effect["set"]["isUnremovable"])
        self.assertEqual(effect["set"]["addProbability"],100)
        writer=TableWriter(self.c.native); writer.add(r)
        row=writer.tables["Skill/DT_SkillData"]["add"][0]["set"]
        self.assertEqual((row["TargetType"],row["isTargetIgnoreSelf"]),("Group",True))
        self.assertEqual(row["effectBundleList"][0]["TargetType"],"SkillTarget")
        self.assertEqual(row["magnification"],0)
        self.assertIn("all other allies",TableWriter.description(r))

    def test_cover_damage_filters_and_default_physical_mode_are_retained(self):
        for mode,types,name in ((None,[1],"Guardian Ward"),(1,[1],"Guardian Ward"),(2,[2],"Spellguard Ward"),(0,[1,2],"Guardian Aegis")):
            with self.subTest(mode=mode):
                params=[1,0,60,60,100,100,2,1]+([] if mode is None else [mode])
                r=self.c.convert(source([[0,3,96,params]]))
                self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
                self.assertEqual(r["components"][0]["replacement"],name)
                self.assertEqual([e["set"]["ParamList"][:2] for e in r["native"]["effects"]],[[d,22] for d in types])

    def test_one_turn_ward_duration_is_displayed_but_instant_recovery_is_not_timed(self):
        r=self.c.convert(source([[0,3,96,[1,0,30,30,20,100,1,1,1]]]))
        self.assertIn("for 1 turn.",TableWriter.description(r))
        r=self.c.convert(source([[1,2,16,[1500]]]))
        self.assertIn("Restores 150 HP",TableWriter.description(r))
        self.assertNotIn("turn",TableWriter.description(r))

    def test_cover_chance_sets_bounded_strength_and_zero_is_a_noop(self):
        for lo,hi,chance,amount in ((50,50,20,4),(100,100,100,25),(0,0,100,10)):
            with self.subTest(chance=chance,lo=lo):
                r=self.c.convert(source([[0,3,96,[1,0,lo,hi,chance,100,3,1,1]]]))
                effect=r["native"]["effects"][0]["set"]
                self.assertEqual(effect["ParamList"][1],amount)
                self.assertEqual((effect["addProbability"],effect["activationProbability"]),(100,100))
        r=self.c.convert(source([[0,3,96,[1,0,50,70,0,100,3,1,1]]]))
        self.assertEqual(r["status"],"noop")
        self.assertFalse(r["components"][0]["effects"])

    def test_targeted_cover_ward_keeps_the_selected_ally_filter(self):
        for side in (2,5):
            with self.subTest(side=side):
                r=self.c.convert(source([[1,side,118,[50,50,100,2,1,0]]]))
                self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
                self.assertEqual(r["components"][0]["semantic"]["protector"]["shape"],"Self")
                self.assertEqual([e["set"]["ParamList"][:2] for e in r["native"]["effects"]],[[1,20],[2,20]])
                writer=TableWriter(self.c.native); writer.add(r)
                row=writer.tables["Skill/DT_SkillData"]["add"][0]["set"]
                self.assertEqual((row["TargetType"],row["isTargetIgnoreSelf"]),("Single",side==5))
                self.assertTrue(all(b["TargetType"]=="SkillTarget" for b in row["effectBundleList"]))

    def test_monster_cover_keeps_its_explicit_damage_type(self):
        for mode,types in ((0,[1,2]),(1,[1]),(2,[2])):
            r=self.c.convert(source([[0,3,142,[1,0,0,100,4,1,mode,0]]],kind="enemy"))
            self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
            self.assertEqual([e["set"]["ParamList"][:2] for e in r["native"]["effects"]],[[d,10] for d in types])
            self.assertTrue(all(e["set"]["effectEndActionNum"]==4 for e in r["native"]["effects"]))

    def test_cover_restrictions_and_unknown_controls_cannot_become_party_wards(self):
        cases=[
            [0,3,96,[1,1,50,70,80,100,3,1,1]],
            [0,3,96,[0,0,50,70,80,100,3,1,1]],
            [1,2,96,[1,0,50,70,80,100,3,1,1]],
            [0,3,96,[1,0,50,70,80,30,3,1,1]],
            [0,3,96,[1,0,70,50,80,100,3,1,1]],
            [0,3,96,[1,0,50,70,80,100,0,1,1]],
            [0,3,96,[True,0,50,70,80,100,3,1,1]],
            [0,3,96,[1,0,50,70,80,100,3,1,3]],
            [1,5,118,[50,50,100,2,0,0]],
            [2,2,118,[50,50,100,2,1,0]],
            [1,6,118,[50,50,100,2,1,0]],
            [0,3,142,[1,0,0,100,4,1,2,1]],
        ]
        for effect in cases:
            with self.subTest(effect=effect):
                r=self.c.convert(source([effect]))
                self.assertFalse(r["validation"]["tableCompatible"],r["issues"])
                self.assertFalse(r["components"][0]["effects"])

    def test_passive_cover_is_decoded_without_granting_a_permanent_party_buff(self):
        for code,damage in ((8,"physical"),(59,"magic")):
            r=self.c.convert(source([[1,2,code,[0,100,50,60,30]]],kind="passive"))
            self.assertFalse(r["validation"]["tableCompatible"])
            semantic=r["components"][0]["semantic"]
            self.assertEqual(semantic["damageTypes"],[damage])
            self.assertEqual((semantic["chance"],semantic["turns"]),(30,-1))
            self.assertEqual(semantic["protected"]["selection"],"attacked_ally_of_protector")
            self.assertFalse(r["components"][0]["effects"])
        for params in ([0,100,50,100],[0,30,70,70,30],[1,100,0,0,5]):
            r=self.c.convert(source([[1,2,8,params]],kind="passive"))
            self.assertEqual(r["status"],"blocked")
            self.assertFalse(r["components"][0]["effects"])

    def test_support_excluding_caster_uses_native_filtered_skill_selection(self):
        r=self.c.convert(source([[2,5,3,[100,0,0,0,3,1]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertTrue(r["native"]["set"]["isTargetIgnoreSelf"])
        effect=r["native"]["effects"][0]
        self.assertEqual(effect["targetBinding"],"skill_selection")
        evidence=effect["targetBindingEvidence"]
        row=self.c.native.skills[self.c.native.skill_ids[evidence["skillId"]]]
        self.assertEqual((row["isTargetIgnoreSelf"],row["TargetType"]),(True,"Group"))
        writer=TableWriter(self.c.native); writer.add(r)
        emitted=writer.tables["Skill/DT_SkillData"]["add"][0]["set"]
        self.assertEqual(emitted["effectBundleList"][0]["TargetType"],"SkillTarget")
        self.assertEqual(writer.bindings[0]["targetBindings"][0]["evidence"],evidence)
        self.assertIn("all other allies",TableWriter.description(r))

    def test_filtered_party_support_can_also_buff_the_caster_explicitly(self):
        r=self.c.convert(source([[2,5,3,[100,0,0,0,3,1]], [0,3,3,[0,0,100,0,3,1]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        writer=TableWriter(self.c.native); writer.add(r)
        emitted=writer.tables["Skill/DT_SkillData"]["add"][0]["set"]
        self.assertTrue(emitted["isTargetIgnoreSelf"])
        self.assertEqual([b["TargetType"] for b in emitted["effectBundleList"]],["SkillTarget","Self"])
        self.assertIn("the user",TableWriter.description(r))

    def test_filtered_effect_overflow_keeps_the_same_selected_recipients(self):
        r=self.c.convert(source([[2,5,3,[100,0,0,0,3,1]]] * 9))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        writer=TableWriter(self.c.native); writer.add(r)
        bundles=writer.tables["Skill/DT_SkillData"]["add"][0]["set"]["effectBundleList"]
        self.assertEqual(len(bundles),3)
        self.assertTrue(all(b["TargetType"]=="SkillTarget" for b in bundles))
        self.assertEqual(len(writer.bindings[0]["targetBindings"]),3)

    def test_incompatible_selection_filters_and_alive_dead_groups_are_held(self):
        for effects in (
            [[2,5,3,[100,0,0,0,3,1]], [2,2,3,[0,0,100,0,3,1]]],
            [[2,2,4,[50]], [2,2,3,[100,0,0,0,3,1]]],
            [[2,1,1,[0,0,0,0,0,0,500,0]], [1,1,24,[0,100,0,0,3,1]]],
        ):
            with self.subTest(effects=effects):
                r=self.c.convert(source(effects))
                self.assertEqual(r["status"],"blocked")
                self.assertTrue(any("targeting jobs" in i or "filters" in i for i in r["issues"]),r["issues"])

    def test_single_damage_can_still_apply_an_implicit_group_debuff(self):
        r=self.c.convert(source([[1,1,1,[0,0,0,0,0,0,500,0]], [2,1,24,[0,100,0,0,3,1]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        writer=TableWriter(self.c.native); writer.add(r)
        row=writer.tables["Skill/DT_SkillData"]["add"][0]["set"]
        self.assertEqual((row["TargetType"],row["effectBundleList"][0]["TargetType"]),("Single","Group"))

    def test_random_support_keeps_its_random_selection(self):
        r=self.c.convert(source([[3,1,6,[100,0,0,0,0,0,0,0]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["set"]["TargetType"],"Random")
        self.assertIn("one random enemy",TableWriter.description(r))

    def test_support_on_either_side_uses_the_selected_recipients(self):
        for shape, expected in ((1,"Single"),(2,"Group")):
            with self.subTest(shape=shape):
                r=self.c.convert(source([[shape,6,16,[1500]]]))
                self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
                writer=TableWriter(self.c.native); writer.add(r)
                row=writer.tables["Skill/DT_SkillData"]["add"][0]["set"]
                self.assertEqual(row["TargetType"],expected)
                self.assertFalse(row["isSameRelationTargetingDisabled"])
                self.assertFalse(row["isHostilityRelationTargetingDisabled"])
                self.assertEqual(row["effectBundleList"][0]["TargetType"],"SkillTarget")
                evidence=r["native"]["effects"][0]["targetBindingEvidence"]
                self.assertTrue(evidence["eitherSide"])
                stock=self.c.native.skills[self.c.native.skill_ids[evidence["skillId"]]]
                self.assertFalse(stock["isSameRelationTargetingDisabled"] or stock["isHostilityRelationTargetingDisabled"])
                self.assertEqual(stock["TargetType"],expected)
                self.assertIn("target",TableWriter.description(r))
                if shape == 2:
                    self.assertIn("on the selected side",TableWriter.description(r))

    def test_unbound_either_side_and_dead_group_filters_remain_held(self):
        for effects in (
            [[2,1,1,[0,0,0,0,0,0,500,0]], [2,6,16,[1500]]],
            [[2,6,4,[50]]],
            [[3,6,16,[1500]]],
        ):
            with self.subTest(effects=effects):
                r=self.c.convert(source(effects))
                self.assertFalse(r["validation"]["tableCompatible"],r["issues"])
                with self.assertRaises(ValueError): TableWriter(self.c.native).add(r)

    def test_resistance_does_not_inflict_ailment(self):
        r = self.c.convert(source([[0,3,2,[100,0,0,0,0,0,0,0]]],kind="passive"))
        e = r["native"]["effects"][0]["set"]
        self.assertEqual(e["EffectType"],"AddStatusConditionRegist")
        self.assertEqual(e["statusCondition"],"None")

    def test_stat_seventh_slot_is_critical_not_agility(self):
        r = self.c.convert(source([[0,3,1,[0,0,0,0,0,0,50]]],kind="passive"))
        self.assertEqual(r["native"]["effects"][0]["set"]["EffectType"],"CriticalRateVariation")

    def test_stone_killer_theme_is_defence(self):
        r = self.c.convert(source([[0,3,105,[10,200]]],kind="passive"))
        self.assertEqual(r["components"][0]["replacement"],"Stalwart Stones")
        self.assertEqual(r["native"]["effects"][0]["set"]["ParamList"][:3],[20,6,2])

    def test_multi_race_killers_share_budget(self):
        r = self.c.convert(source([[0,3,11,[[1,8],[200,200],[200,200]]]],kind="passive"))
        self.assertEqual(sum(e["set"]["ParamList"][0] for e in r["native"]["effects"]),20)

    def test_all_race_killers_not_twelve_full_bonuses(self):
        r = self.c.convert(source([[2,2,92,[[0,200]]+[-1]*7+[3,1]]]))
        self.assertEqual(r["components"][0]["replacement"],"Myriad Mastery")
        self.assertEqual(sum(e["set"]["ParamList"][0] for e in r["native"]["effects"]),20)

    def test_race_attacks_keep_the_one_x_base_and_reward_the_caster(self):
        for code,race,coefficient,stat,amount in ((22,10,350,6,20),(23,12,180,8,8)):
            with self.subTest(code=code):
                r=self.c.convert(source([[2,1,code,[race,0,0,coefficient]]]))
                normal=self.c.convert(source([[2,1,1,[0,0,0,0,0,0,100]]] if code==22 else [[2,1,15,[0,0,0,0,0,100]]]))
                self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
                self.assertEqual(r["native"]["set"]["magnification"],normal["native"]["set"]["magnification"])
                self.assertEqual(r["components"][0]["actions"][0]["multiple"],1)
                self.assertEqual(r["components"][0]["semantic"]["raceMultiple"],coefficient/100)
                e=r["native"]["effects"][0]
                self.assertEqual(e["set"]["ParamList"][:3],[amount,stat,2])
                self.assertEqual((e["target"]["shape"],e["target"]["relation"]),("Self","Friendlies"))
                self.assertEqual(e["set"]["effectEndActionNum"],1)
                self.assertEqual(e["activeTiming"],"AfterDamageCalculation")
                self.assertEqual(r["native"]["sequence"]["hitFrames"],[12,24])
                self.assertNotIn("Stoned",[e["set"]["statusCondition"] for e in r["native"]["effects"]])

    def test_race_attack_without_a_bonus_keeps_only_its_base_damage(self):
        for coefficient in (100,105):
            r=self.c.convert(source([[2,1,22,[1,0,0,coefficient]]]))
            self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
            self.assertEqual(r["components"][0]["actions"][0]["multiple"],1)
            self.assertFalse(r["native"]["effects"])

    def test_unknown_race_controls_and_conditional_penalties_remain_held(self):
        for p in ([1,1,0,350],[1,0,1,350],[1,False,0,350],[0,0,0,350],[13,0,0,350],[1,0,0,50],[1,0,0,-1],[1,0,0,350,1]):
            with self.subTest(p=p):
                r=self.c.convert(source([[2,1,22,p]]))
                self.assertFalse(r["validation"]["tableCompatible"])
                self.assertFalse(r["components"][0]["actions"])
                self.assertFalse(r["components"][0]["effects"])

    def test_multiple_race_attack_clauses_share_one_reward_budget(self):
        r=self.c.convert(source([[2,1,22,[race,0,0,100000]] for race in (1,8,10)],
            attack_frames=[[10],[20],[30]],attack_damage=[[100]]*3))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        effects=r["native"]["effects"]
        self.assertEqual([e["set"]["ParamList"][:2] for e in effects],[[7,5],[7,7],[6,6]])
        self.assertEqual(sum(e["set"]["ParamList"][0] for e in effects),20)
        self.assertEqual([e["order"] for e in effects],[[-1],[-1],[3]])
        self.assertEqual([e["activeTiming"] for e in effects],["BeforeDamageCalculation","BeforeDamageCalculation","AfterDamageCalculation"])
        self.assertEqual([e["set"]["effectEndActionNum"] for e in effects],[2,2,1])
        self.assertEqual(r["native"]["set"]["hitCount"],3)
        for weight in r["native"]["set"]["hitDamageRatioList"][:3]:self.assertAlmostEqual(weight,1/3)

    def test_repeated_race_clauses_retain_hits_without_duplicating_the_reward(self):
        r=self.c.convert(source([[2,1,22,[1,0,0,6000]]]*3,
            attack_frames=[[10],[20],[30]],attack_damage=[[100]]*3))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(len(r["native"]["effects"]),1)
        self.assertEqual(r["native"]["effects"][0]["set"]["ParamList"][0],20)
        self.assertEqual(len(r["native"]["effects"][0]["raceDamageSources"]),3)
        self.assertEqual(r["native"]["sequence"]["hitFrames"],[10,20,30])

    def test_race_lb_uses_one_base_damage_budget_with_the_source_portions(self):
        r=self.c.convert(source([[2,1,22,[8,0,0,20000]],[2,1,1,[0,0,0,0,0,0,16000]]],kind="lb",
            attack_frames=[[12],[24]],attack_damage=[[100],[100]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["set"]["magnification"],self.c.native.cloud["magnification"])
        self.assertAlmostEqual(r["native"]["set"]["hitDamageRatioList"][0],1/161)
        self.assertAlmostEqual(r["native"]["set"]["hitDamageRatioList"][1],160/161)
        self.assertEqual(r["native"]["effects"][0]["activeTiming"],"BeforeDamageCalculation")

    def test_inlined_race_attacks_rebuild_one_reward_for_the_parent(self):
        a=source([[2,1,22,[1,0,0,6000]]],sid="200",attack_frames=[[10]],attack_damage=[[100]])
        b=source([[2,1,22,[10,0,0,6000]]],sid="300",attack_frames=[[20]],attack_damage=[[100]])
        parent=source([[0,3,71,[200,1]],[0,3,71,[300,1]]],sid="100")
        converter,_=self.catalog_converter(parent,a,b)
        r=converter.convert(parent)
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual([e["set"]["ParamList"][:2] for e in r["native"]["effects"]],[[10,5],[10,6]])
        self.assertEqual(r["native"]["sequence"]["hitFrames"],[10,20])
        self.assertEqual({s["source"] for s in r["native"]["effects"][0]["raceDamageSources"]},{a.key,b.key})
        self.assertEqual(r["components"][0]["expanded"]["native"]["effects"][0]["set"]["ParamList"][0],20)

    def test_race_reward_does_not_move_unrelated_interleaved_effects(self):
        r=self.c.convert(source([[2,1,22,[1,0,0,6000]], [0,3,3,[100,0,0,0,3,1]],
            [2,1,1,[0,0,0,0,0,0,500]]],attack_frames=[[10],[15],[20]],attack_damage=[[100],[100],[100]]))
        self.assertFalse(r["validation"]["tableCompatible"])
        self.assertTrue(any("ordered application jobs" in i for i in r["issues"]))

    def test_race_reward_is_emitted_after_later_source_effects(self):
        r=self.c.convert(source([[2,1,22,[10,0,0,6000]], [0,3,3,[100,0,0,0,3,1]]],
            attack_frames=[[12,24],[]],attack_damage=[[30,70],[]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        effects=r["native"]["effects"]
        self.assertEqual([e["set"]["effectEndActionNum"] for e in effects],[3,1])
        self.assertEqual(effects[-1]["generated"],"race_damage_reward")
        self.assertFalse(effects[0].get("generated"))

    def test_all_races_in_one_attack_share_myriad_mastery(self):
        r=self.c.convert(source([[2,1,22,[race,0,0,180]] for race in range(1,13)],
            attack_frames=[[i] for i in range(12)],attack_damage=[[100]]*12))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(len(r["native"]["effects"]),4)
        self.assertEqual(sum(e["set"]["ParamList"][0] for e in r["native"]["effects"]),8)
        self.assertEqual(r["native"]["set"]["hitCount"],12)

    def test_small_myriad_budget_keeps_integer_remainders_without_zero_effects(self):
        r=self.c.convert(source([[0,3,105,[0,30]]],kind="passive"))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual([e["set"]["ParamList"][0] for e in r["native"]["effects"]],[1,1,1])

    def test_zero_killer_budgets_remain_explicit_noops(self):
        for amount in (0,5):
            for kind,effect in (("passive",[0,3,105,[10,amount]]),("ability",[2,2,92,[[10,amount]]+[-1]*7+[3,1]])):
                r=self.c.convert(source([effect],kind=kind))
                self.assertEqual(r["status"],"noop")
                self.assertEqual(r["components"][0]["raw"],effect)
                self.assertFalse(r["components"][0]["effects"])

    def test_unknown_preserves_raw_and_blocks_export(self):
        raw = [2,1,99999,["opaque",[1,2]]]
        r = self.c.convert(source([raw]))
        self.assertEqual(r["status"],"blocked")
        self.assertEqual(r["components"][0]["raw"],raw)
        with self.assertRaises(ValueError):
            TableWriter(self.c.native).add(r)

    def test_malformed_component_does_not_disappear(self):
        r = self.c.convert(source([[1,2,3],None,[2,1,"15",[]]]))
        self.assertEqual(len(r["components"]),3)
        self.assertEqual(r["status"],"blocked")

    def test_random_status_is_not_all_statuses(self):
        r = self.c.convert(source([[2,1,34,[100]*8+[0,1]]]))
        self.assertEqual(r["status"],"blocked")
        self.assertFalse(r["components"][0]["effects"])

    def test_mixed_heal_and_damage_uses_separate_source_timed_applications(self):
        r = self.c.convert(source([[2,1,15,[0,0,0,0,0,300]], [2,2,2,[0,0,1000,300]]],
                                  attack_frames=[[12],[24]],attack_damage=[[100],[100]]))
        self.assertTrue(r['validation']['tableCompatible'],r['issues'])
        self.assertEqual(r['native']['sequence']['hitFrames'],[12,24])
        self.assertEqual(r['native']['sequence']['hitWeights'],[1.,0.])
        self.assertEqual(r['native']['applications'][0]['set']['magnification'],70)
        self.assertEqual(r['native']['applications'][0]['set']['parameterVariationType'],'Increase')

    def test_multicomponent_lb_has_one_total_budget(self):
        r = self.c.convert(source([[2,1,15,[0,0,0,0,0,100]], [2,1,15,[0,0,0,0,0,300]]],kind="lb",
                                  attack_frames=[[12],[24]],attack_damage=[[100],[100]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["set"]["magnification"],self.c.native.cloud["magnification"])
        self.assertEqual(r["native"]["set"]["hitDamageRatioList"][:2],[.25,.75])

    def test_gauge_cost_on_regular_skill_binds_cost_and_affordability(self):
        r = self.c.convert(source([[2,1,15,[0,0,0,0,0,100]]],lb_cost=20))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["resourceCosts"],[{"costType":"LB","Cost":100}])
        self.assertEqual(r["native"]["set"]["Cost"],15)
        writer = TableWriter(self.c.native)
        sid = writer.add(r)
        patch = writer.patch(ROOT/"build/abilities/fixture")
        general = next(t for t in patch["tables"] if t["asset"].endswith("DT_SkillGeneralData"))["set"][0]["set"]
        self.assertIn({"SkillId":sid,"costType":"LB","Cost":100},general["additionalCostData"])
        self.assertIn({"SkillId":sid,"costType":"LB","Cost":100},general["costCheckData"])
        self.assertIn(sid,general["equipperActionVisionSkills"])
        self.assertIn(414610,general["equipperActionVisionSkills"])
        for field, values in general.items():
            self.assertEqual(values[:len(self.c.native.general[field])],self.c.native.general[field])

    def test_cooldown_and_boost_are_never_unconditional(self):
        cooldown = self.c.convert(source([[0,3,130,[1234,0,[4,3],0]]]))
        self.assertEqual(cooldown["dependencies"][0]["id"],"1234")
        self.assertEqual(cooldown["status"],"blocked")
        boost = self.c.convert(source([[0,3,110,[100]]],kind="passive"))
        self.assertEqual(boost["status"],"blocked")
        self.assertFalse(boost["components"][0]["effects"])

    def catalog_converter(self, *records):
        catalog = SourceCatalog()
        self.addCleanup(catalog.close)
        for record in records:
            catalog.add(record)
        catalog.finish()
        return Converter(native=self.c.native, resolver=catalog), catalog

    def test_immediate_child_preserves_cost_frames_element_and_order(self):
        child = source([[0,3,3,[100,0,0,0,3,1]], [2,1,15,[0,0,0,0,0,1000]]], sid="200",
                       mp_cost=99, element_inflict=["Fire"], attack_frames=[[],[18,42]], attack_damage=[[],[20,80]])
        parent = source([[0,3,71,[200,1]]], sid="100", mp_cost=20, attack_frames=[[]], attack_damage=[[]])
        converter, catalog = self.catalog_converter(parent, child)
        result = converter.convert(parent)
        self.assertTrue(result["validation"]["tableCompatible"],result["issues"])
        self.assertEqual(result["native"]["set"]["Cost"],30)
        self.assertEqual(result["native"]["set"]["element"],"Fire")
        self.assertEqual(result["native"]["set"]["hitDamageRatioList"][:2],[.2,.8])
        self.assertEqual(result["native"]["sequence"]["hitFrames"],[18,42])
        self.assertEqual(result["native"]["effects"][0]["activeTiming"],"BeforeDamageCalculation")
        self.assertEqual(result["components"][0]["expanded"]["source"]["key"],child.key)
        self.assertEqual(result["components"][0]["raw"],parent.data["effects_raw"][0])
        graph = SkillGraph(); graph.add(result)
        edge = graph.resolve(catalog)["edges"][0]
        self.assertEqual(edge["to"],child.key)
        self.assertTrue(edge["outsideSelection"])

    def test_nested_proxy_cycle_and_child_restrictions_hold_parent(self):
        a = source([[0,3,71,[200,1]]],sid="100")
        b = source([[0,3,71,[100,1]]],sid="200")
        c, _ = self.catalog_converter(a,b)
        result = c.convert(a)
        self.assertEqual(result["status"],"blocked")
        inner = result["components"][0]["expanded"]["components"][0]
        self.assertTrue(any("cycle" in issue for issue in inner["issues"]))
        restricted = source([[0,3,130,[300,0,[4,3],0]]],sid="200")
        c, _ = self.catalog_converter(a,restricted)
        result = c.convert(a)
        self.assertEqual(result["status"],"blocked")
        self.assertEqual(result["components"][0]["expanded"]["dependencies"][0]["condition"]["cooldownTurns"],5)

    def test_reference_lookup_obeys_revision_and_monster_namespace(self):
        player = source([[0,3,3,[100,0,0,0,3,1]]],sid="200")
        enemy = source([[2,1,15,[0,0,0,0,0,1000]]],sid="200",kind="enemy")
        parent = source([[0,3,71,[200,1]]],sid="100")
        c, catalog = self.catalog_converter(player,enemy,parent)
        self.assertEqual(c.convert(parent)["native"]["set"]["magnification"],0)
        enemy_parent = source(parent.data["effects_raw"],sid="100",kind="enemy")
        self.assertGreater(c.convert(enemy_parent)["native"]["set"]["magnification"],0)
        parent.source = "ANOTHER_REVISION"
        self.assertEqual(c.convert(parent)["status"],"blocked")
        with self.assertRaisesRegex(ValueError,"Missing"):
            catalog.resolve(parent.provenance(),{"kind":"skill","id":"200"})

    def test_proxy_child_gauge_cost_and_interleaved_mechanics_stay_held(self):
        parent = source([[0,3,71,[200,1]]],sid="100")
        costed = source([[2,1,15,[0,0,0,0,0,100]]],sid="200",lb_cost=20)
        c, _ = self.catalog_converter(parent,costed)
        self.assertEqual(c.convert(parent)["status"],"blocked")
        mixed = source([[2,1,15,[0,0,0,0,0,100]], [0,3,3,[100,0,0,0,3,1]],
                        [2,1,15,[0,0,0,0,0,100]]],sid="200",
                       attack_frames=[[12],[],[24]],attack_damage=[[100],[],[100]])
        c, _ = self.catalog_converter(parent,mixed)
        result = c.convert(parent)
        self.assertEqual(result["status"],"blocked")
        self.assertTrue(any("ordered application" in issue for issue in result["components"][0]["expanded"]["issues"]))

    def test_prerequisite_edges_are_not_execution_cycles(self):
        a = self.c.convert(source([[0,3,130,[200,0,[4,3],0]]],sid="100"))
        b = self.c.convert(source([[0,3,130,[100,0,[4,3],0]]],sid="200"))
        b["dependencies"][0]["relation"] = "prerequisite"
        graph = SkillGraph(); graph.add(a); graph.add(b)
        self.assertFalse(graph.resolve()["cycles"])
        self.assertEqual(len(graph.resolve()["edges"]),2)

    def test_chance_healing_is_not_a_child_action_or_damage(self):
        r = self.c.convert(source([[2,2,38,[0,0,100,100,50,5000040,"message"]]]))
        self.assertEqual(r["status"],"replaced")
        self.assertEqual(r["native"]["set"]["magnification"],0)
        self.assertFalse(r["dependencies"])
        e = r["native"]["effects"][0]["set"]
        self.assertEqual((e["EffectType"],e["addProbability"],e["ParamList"][:3]),("ParameterVariation",50,[6,1,2]))
        r = self.c.convert(source([[2,2,38,[0,0,100,100,100,5000040,"message"]]],
                                  attack_frames=[[12]],attack_damage=[[100]]))
        self.assertEqual(r["native"]["set"]["parameterVariationType"],"Increase")
        r = self.c.convert(source([[2,2,38,[0,0,0,0,0,5000040,"message"]]]))
        self.assertEqual(r["status"],"noop")

    def test_normal_counter_rolls_on_trigger_and_keeps_native_child(self):
        r = self.c.convert(source([[0,3,12,[30,100,0]]],kind="passive"))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        e = r["native"]["effects"][0]
        self.assertEqual(e["set"]["EffectType"],"Counter")
        self.assertEqual((e["set"]["addProbability"],e["set"]["activationProbability"]),(100,30))
        self.assertEqual((e["set"]["ParamList"][0],e["set"]["ParamList"][7]),(6,400120))
        self.assertEqual(e["nativeSkillReferences"],[400120])
        r = self.c.convert(source([[0,3,50,[40,1,0,0]]],kind="passive"))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["effects"][0]["set"]["ParamList"][7],400130)
        self.assertIn("40% chance to counter magic",TableWriter.description(r))

    def test_timed_normal_counter_and_finite_counter_are_distinct(self):
        r = self.c.convert(source([[0,3,119,[30,1,100,3,1]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        e = r["native"]["effects"][0]["set"]
        self.assertEqual((e["proceedTiming"],e["effectEndActionNum"]),("BeginTurn",3))
        r = self.c.convert(source([[0,3,119,[30,1,100,3,1,2]]]))
        self.assertEqual(r["status"],"blocked")
        self.assertFalse(r["components"][0]["effects"])
        r = self.c.convert(source([[0,3,12,[30,500,0]]],kind="passive"))
        self.assertEqual(r["status"],"blocked")

    def test_repeated_instant_recovery_components_are_not_dropped(self):
        r = self.c.convert(source([[2,2,64,[10,0]],[2,2,64,[10,0]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(len(r["native"]["effects"]),2)
        writer = TableWriter(self.c.native); writer.add(r)
        self.assertEqual(len(writer.tables["Skill/DT_SkillData"]["add"][0]["set"]["effectBundleList"]),2)

    def test_extended_hits_preserve_every_frame_weight_and_one_damage_budget(self):
        for count in (30,31,32,33,36,39,40,48,52,54,60,100):
            for kind in ("ability","lb"):
                with self.subTest(count=count,kind=kind):
                    frames=list(range(12,12+count*3,3))
                    weights=[1]*(count-1)+[count+1]
                    r=self.c.convert(source([[2,1,15,[0,0,0,0,0,100]]],kind=kind,
                                           attack_frames=[frames],attack_damage=[weights]))
                    self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
                    row=r["native"]["set"]
                    self.assertEqual(row["hitCount"],count)
                    self.assertEqual(r["native"]["sequence"]["hitFrames"],frames)
                    self.assertEqual(len(row["hitDamageRatioList"]),max(count,31))
                    self.assertEqual(row["hitDamageRatioList"][:count],[v/(2*count) for v in weights])
                    self.assertAlmostEqual(sum(row["hitDamageRatioList"]),1.)
                    if kind=="lb":
                        self.assertEqual(row["magnification"],self.c.native.cloud["magnification"])

    def test_native_hit_arrays_reject_missing_invalid_or_unused_damage_weights(self):
        original=self.c.convert(source([[2,1,15,[0,0,0,0,0,100]]]))["native"]["set"]
        for hits,weights in ((True,[1]),(0,[1]),(2147483648,[1]),(2,[1]),(1,[.5,.5]),
                             (2,[-1,2]),(1,[float("nan")]),(1,[float("inf")]),(1,[True]),(1,[.9])):
            with self.subTest(hits=hits,weights=weights):
                row={**original,"hitCount":hits,"hitDamageRatioList":weights}
                with self.assertRaises(ValueError):
                    self.c.native.validate_skill(row)

    def test_extended_multi_component_timeline_keeps_component_budget_shares(self):
        r=self.c.convert(source([[2,1,15,[0,0,0,0,0,100]],[2,1,15,[0,0,0,0,0,300]]],
                                attack_frames=[list(range(0,40,2)),list(range(1,41,2))],
                                attack_damage=[[1]*20,[1]*20]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["sequence"]["hitFrames"],list(range(40)))
        weights=r["native"]["set"]["hitDamageRatioList"]
        self.assertEqual(len(weights),40)
        self.assertAlmostEqual(sum(weights[::2]),.25)
        self.assertAlmostEqual(sum(weights[1::2]),.75)

    def test_fixed_damage_cannot_repeat_one_budget_through_unweighted_hits(self):
        for kind in ("ability","enemy","lb"):
            for frames,weights in (([12,24],[50,50]),([12,24],[20,80]),([12]*40,[1]*40)):
                with self.subTest(kind=kind,frames=frames):
                    result=self.c.convert(source([[2,1,41,[10000]]],kind=kind,
                                                 attack_frames=[frames],attack_damage=[weights]))
                    self.assertEqual(result["status"],"blocked")
                    self.assertTrue(any("Fixed damage bypasses native hit weights" in issue for issue in result["issues"]))
                    with self.assertRaises(ValueError):
                        TableWriter(self.c.native).add(result)
            single=self.c.convert(source([[2,1,41,[10000]]],kind=kind,
                                         attack_frames=[[12]],attack_damage=[[100]]))
            self.assertTrue(single["validation"]["tableCompatible"],single["issues"])
            self.assertEqual(single["native"]["set"]["damageCalcType"],"Fixed")
            self.assertEqual(single["native"]["set"]["DamageType"],"None")

    def test_immediate_child_cannot_bypass_fixed_multi_hit_budget_hold(self):
        child=source([[2,1,41,[10000]]],sid="200")
        with SourceCatalog() as catalog:
            catalog.add(child);catalog.finish()
            result=Converter(resolver=catalog).convert(source([[0,3,71,[200,1]]],sid="100"))
        self.assertEqual(result["status"],"blocked")
        self.assertTrue(any("blocking issues" in issue for issue in result["issues"]))

    def test_master_frames_and_flag_correction(self):
        row = {"ability_id":"1","is_active":"1","effect_type":"15","effect_param":"0,0,0,0,0,100",
               "target_range":"2","target":"1","attack_frames":"12:30:2:2-24:70:2:2","mp_cost":"7"}
        r = master_record(row,"F_ABILITY_MST",{"active":True,"effects_raw":[[2,1,15,[]]]})
        self.assertEqual(r.kind,"ability")
        self.assertEqual(r.data["attack_frames"],[[12,24]])
        self.assertEqual(r.data["mp_cost"],7)
        self.assertTrue(r.data["_activeFlagCorrected"])

    def test_all_lb_levels_and_versions_stay_distinct(self):
        d = {"1":{"name":"LB","levels":{"1":{"cost":10,"effects_raw":[[0,3,0,[]]]},"2":{"cost":20,"effects_raw":[[0,3,0,[]]]}}}}
        records = list(structured_records(d,"JP","limitbursts","fixture"))
        self.assertEqual(len({r.key for r in records}),2)
        self.assertEqual([r.data["lb_cost"] for r in records],[10,20])

    def test_writer_is_native_patch_and_reuses_effect_ids(self):
        result = self.c.convert(source([[1,2,4,[50]]],sid="100"))
        writer = TableWriter(self.c.native)
        writer.add(result)
        result2 = deepcopy(result); result2["source"]["key"] += "_2"
        writer.add(result2)
        self.assertEqual(len(writer.tables["Skill/DT_SkillEffectData"]["add"]),1)
        self.assertEqual(len(writer.tables["Skill/DT_SkillData"]["add"]),2)
        for patch in writer.tables["Skill/DT_SkillData"]["add"]:
            self.c.native.validate_skill(patch["set"])
            self.assertIsInstance(patch["set"]["Name"],str)
            self.assertEqual(patch["set"]["playSequencerId"],-1)
        self.assertEqual(writer.bindings[0]["owner"],"equipping_actor")
        self.assertEqual(writer.bindings[0]["runtimeValidation"],"not_run")

    def test_six_stat_passive_retains_every_effect_in_native_bundle_array(self):
        r = self.c.convert(source([[0,3,1,[100,100,100,100,100,100]]],kind="passive"))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        writer = TableWriter(self.c.native)
        writer.add(r)
        rows = writer.tables["Skill/DT_SkillEffectData"]["add"]
        effects = {row["set"]["ID"]:row['set'] for row in rows}
        bundles=writer.tables['Skill/DT_PassiveSkillData']['add'][0]['set']['effectBundleList']
        self.assertEqual(len(bundles),6)
        self.assertEqual({effects[b['effectId']]['ParamList'][1] for b in bundles},{1,2,5,6,7,8})
        self.assertTrue(all(b['TargetType']=='Self' and b['passiveSkillAddTiming']=='SpawnUnit' for b in bundles))

    def test_scalar_and_vector_killers_have_identical_mechanics(self):
        a = self.c.convert(source([[0,3,11,[10,200,0]]],kind="passive"))
        b = self.c.convert(source([[0,3,11,[[10],[200],[0]]]],kind="passive"))
        self.assertEqual(a["native"],b["native"])

    def test_vigilance_prevents_sneak_attacks_without_changing_encounters(self):
        result=self.c.convert(source([[0,3,23,[100,1]]],kind="passive"))
        self.assertTrue(result["validation"]["tableCompatible"],result["issues"])
        effects=result["native"]["effects"]
        self.assertEqual(len(effects),1)
        self.assertEqual((effects[0]["set"]["EffectType"],effects[0]["set"]["ParamList"][:2]),("Preemtive",[1,0]))
        self.assertEqual(TableWriter.description(result),"Prevents enemy sneak attacks.")
        partial=self.c.convert(source([[0,3,23,[50,1]]],kind="passive"))
        self.assertEqual(partial["status"],"blocked")
        self.assertFalse(partial["components"][0]["effects"])

    def test_encounter_rate_preserves_direction_and_uses_remaining_percentage(self):
        for change,percent in ((-100,0),(-80,20),(-50,50),(-30,70),(-25,75),(25,125),(50,150),(200,150)):
            with self.subTest(change=change):
                result=self.c.convert(source([[0,3,43,[change]]],kind="passive"))
                self.assertTrue(result["validation"]["tableCompatible"],result["issues"])
                effect=result["native"]["effects"][0]["set"]
                self.assertEqual((effect["EffectType"],effect["ParamList"][0]),("EncountRatio",percent))
                description=TableWriter.description(result)
                self.assertIn("Prevents random encounters" if percent==0 else "Reduces random encounter rate" if percent<100 else "Increases random encounter rate",description)
                self.assertNotIn("sneak",description)
                self.assertEqual(result["components"][0]["semantic"]["sourceChangePercent"],change)

    def test_reward_bonuses_use_total_multipliers_with_native_caps(self):
        for code,kind,reward in ((37,"MoneyUp","gil"),(45,"ExperienceUp","experience")):
            for bonus in (10,20,22,25,50,100,2000):
                with self.subTest(code=code,bonus=bonus):
                    result=self.c.convert(source([[0,3,code,[bonus]]],kind="passive"))
                    self.assertTrue(result["validation"]["tableCompatible"],result["issues"])
                    effect=result["native"]["effects"][0]["set"]
                    self.assertEqual((effect["EffectType"],effect["ParamList"][0]),(kind,100+min(100,bonus)))
                    self.assertEqual(TableWriter.description(result),f"Increases {reward} earned from battles by {min(100,bonus)}%.")
                    self.assertEqual(result["components"][0]["semantic"]["sourceBonusPercent"],bonus)

    def test_steal_success_scales_only_the_decoded_control_variant(self):
        for bonus,amount in ((20,10),(100,50),(200,50)):
            with self.subTest(bonus=bonus):
                result=self.c.convert(source([[0,3,16,[bonus,0]]],kind="passive"))
                self.assertTrue(result["validation"]["tableCompatible"],result["issues"])
                effect=result["native"]["effects"][0]["set"]
                self.assertEqual((effect["EffectType"],effect["ParamList"][0]),("StealRate",amount))
        held=self.c.convert(source([[0,3,16,[100,100]]],kind="passive"))
        self.assertEqual(held["status"],"blocked")
        self.assertEqual(held["components"][0]["semantic"]["sourceControl"],100)
        self.assertFalse(held["components"][0]["effects"])

    def test_gil_after_item_theft_keeps_its_trigger_and_does_not_boost_rare_steals(self):
        result=self.c.convert(source([[0,3,46,[50,100]]],kind="passive"))
        self.assertEqual(result["status"],"blocked")
        component=result["components"][0]
        self.assertEqual(component["semantic"],{"kind":"gil_on_item_steal","minimumPercent":50,"maximumPercent":100,"trigger":"successful_item_steal"})
        self.assertFalse(component["effects"])
        self.assertFalse(component["actions"])

    def test_item_drop_rates_retain_the_common_and_rare_scope(self):
        for bonus in (10,25,50,100):
            with self.subTest(bonus=bonus):
                result=self.c.convert(source([[0,3,47,[bonus,bonus]]],kind="passive"))
                self.assertTrue(result["validation"]["tableCompatible"],result["issues"])
                effect=result["native"]["effects"][0]["set"]
                self.assertEqual((effect["EffectType"],effect["ParamList"][0]),("ItemDropUp",min(25,bonus)))
                self.assertIn(f"by {min(25,bonus)}%",TableWriter.description(result))
        for parameters in ([50],[50,0],[0,50],[100,50]):
            with self.subTest(parameters=parameters):
                result=self.c.convert(source([[0,3,47,parameters]],kind="passive"))
                self.assertEqual(result["status"],"blocked")
                self.assertFalse(result["components"][0]["effects"])
                self.assertIn("drop-category",result["issues"][0])

    def test_zero_rate_bonuses_do_not_grant_stock_benefits(self):
        for code,parameters in ((23,[0,1]),(43,[0]),(37,[0]),(45,[0]),(16,[0,0]),(16,[1,0]),(46,[0,0]),(47,[0,0]),(47,[0])):
            with self.subTest(code=code,parameters=parameters):
                result=self.c.convert(source([[0,3,code,parameters]],kind="passive"))
                self.assertEqual(result["status"],"noop",result["issues"])
                self.assertFalse(result["components"][0]["effects"])

    def test_malformed_rate_parameters_stay_held_without_partial_effects(self):
        for code,parameters in ((23,[100]),(23,[100,0]),(23,[101,1]),(43,[-101]),(43,[-30,0]),
                (37,[-1]),(45,[True]),(45,[20,0]),(16,[100,0,0]),(16,[-1,0]),(46,[100,50]),
                (46,[50]),(46,[50,101]),(47,[50,-1]),(47,[25,25,0])):
            with self.subTest(code=code,parameters=parameters):
                result=self.c.convert(source([[0,3,code,parameters]],kind="passive"))
                self.assertEqual(result["status"],"blocked")
                self.assertFalse(result["components"][0]["effects"])

    def test_scalar_zero_killer_subtypes_expand_without_losing_race_bonuses(self):
        for parameters, expanded in (([[4,10],[75,50],0],[[4,10],[75,50],[0,0]]),
                                     ([[1,5],0,[50,75]],[[1,5],[0,0],[50,75]]),
                                     ([list(range(1,13)),[100]*12,0],[list(range(1,13)),[100]*12,[0]*12])):
            with self.subTest(parameters=parameters):
                raw=[[0,3,11,parameters]]
                actual=self.c.convert(source(raw,kind="passive"))
                expected=self.c.convert(source([[0,3,11,expanded]],kind="passive"))
                self.assertTrue(actual["validation"]["tableCompatible"],actual["issues"])
                self.assertEqual(actual["native"],expected["native"])
                self.assertEqual(actual["components"][0]["raw"],raw[0])
                entries=actual["components"][0]["semantic"]["sourceEntries"]
                self.assertEqual(entries,[{"race":race,"physical":physical,"magical":magical}
                    for race,physical,magical in zip(*expanded)])

    def test_shared_nonzero_scalar_killers_keep_one_total_budget(self):
        actual=self.c.convert(source([[0,3,11,[[5,8],25,0]]],kind="passive"))
        expected=self.c.convert(source([[0,3,11,[[5,8],[25,25],[0,0]]]],kind="passive"))
        self.assertTrue(actual["validation"]["tableCompatible"],actual["issues"])
        self.assertEqual(actual["native"],expected["native"])
        self.assertEqual([e["set"]["ParamList"][0] for e in actual["native"]["effects"]],[1,1])
        self.assertEqual(actual["components"][0]["semantic"]["sourceEntries"],
            [{"race":5,"physical":25,"magical":0},{"race":8,"physical":25,"magical":0}])

    def test_killer_array_mismatches_and_invalid_bonuses_stay_held(self):
        for parameters in ([[1,2],[25],0], [[1,2],[25,25],[0]], [[1,2],[],0],
                           [[1,2],True,0], [[1,2],[25,False],0], [[1,2],-25,0],
                           [[1,2],[25,-1],0], [[1,13],25,0], [[1,2],25,0,99]):
            with self.subTest(parameters=parameters):
                result=self.c.convert(source([[0,3,11,parameters]],kind="passive"))
                self.assertEqual(result["status"],"blocked")
                self.assertFalse(result["components"][0]["effects"])
                self.assertFalse(result["components"][0]["actions"])

    def test_known_zero_padding_keeps_existing_killer_mechanics(self):
        for parameters in ([7,50,50],[[1,3,7],[50,50,100],[50,50,100]]):
            expected=self.c.convert(source([[0,3,11,parameters]],kind="passive"))
            for padding in ([0],[0,0,0]):
                with self.subTest(parameters=parameters,padding=padding):
                    actual=self.c.convert(source([[0,3,11,parameters+padding]],kind="passive"))
                    self.assertTrue(actual["validation"]["tableCompatible"],actual["issues"])
                    self.assertEqual(actual["native"],expected["native"])
                    self.assertEqual(actual["components"][0]["semantic"]["sourceControlParameters"],padding)
        for padding in ([1],[True],[0,0],[0,0,1],[0,0,0,0]):
            with self.subTest(padding=padding):
                actual=self.c.convert(source([[0,3,11,[7,50,50]+padding]],kind="passive"))
                self.assertEqual(actual["status"],"blocked")
                self.assertFalse(actual["components"][0]["effects"])

    def test_equipment_killer_scalars_keep_the_condition_and_quarter_budget(self):
        parameters=[[2,8],list(range(1,13)),100,0]
        actual=self.c.convert(source([[0,3,75,parameters]],kind="passive"))
        expected=self.c.convert(source([[0,3,75,[[2,8],list(range(1,13)),[100]*12,[0]*12]]],kind="passive"))
        self.assertTrue(actual["validation"]["tableCompatible"],actual["issues"])
        self.assertEqual(actual["native"],expected["native"])
        self.assertEqual(sum(e["set"]["ParamList"][0] for e in actual["native"]["effects"]),2)
        semantic=actual["components"][0]["semantic"]
        self.assertEqual((semantic["equipmentCondition"],semantic["replacementScale"]),([2,8],.25))
        self.assertTrue(all(e["physical"]==100 and e["magical"]==0 for e in semantic["sourceEntries"]))
        self.assertEqual(actual["components"][0]["replacement"],"Weapon Mastery")
        for invalid in ([8,[1,2],[100],0],[8,[1,2],100,[0]],[8,[1,2],100,0,0]):
            with self.subTest(parameters=invalid):
                result=self.c.convert(source([[0,3,75,invalid]],kind="passive"))
                self.assertEqual(result["status"],"blocked")
                self.assertFalse(result["components"][0]["effects"])

    def test_client_nested_parameters_follow_source_delimiter_order(self):
        from ability_converter.sources import parameters
        self.assertEqual(parameters("1:2&3:4,5;6"),[[[1,2],[3,4]],[5,6]])

    def test_all_mp_damage_cannot_become_free_damage(self):
        r = self.c.convert(source([[2,1,169,[3,100,2,100]]],mp_cost=0))
        self.assertEqual(r["status"],"blocked")
        self.assertTrue(any("all remaining MP" in i for i in r["issues"]))

    def test_opcode_102_multicast_variant_does_not_deal_damage(self):
        r = self.c.convert(source([[0,3,102,[[1,2,3],0,0,3,0,1]]]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        self.assertEqual(r["native"]["set"]["magnification"],0)
        self.assertEqual(r["components"][0]["replacement"],"Quickcast")

    def test_native_parameters_are_integers_before_serialization(self):
        r = self.c.convert(source([[0,3,11,[[1,2,3,4,5,6],[250]*6,[250]*6]]],kind="passive"))
        def walk(effects):
            for effect in effects:
                self.assertTrue(all(type(v) is int for v in effect["set"]["ParamList"]))
                walk(effect.get("children",[]))
        self.assertTrue(r["validation"]["tableCompatible"],r["issues"])
        walk(r["native"]["effects"])

    def test_equipment_mastery_discloses_reduced_unconditional_bonus(self):
        r = self.c.convert(source([[0,3,6,[4,100,0,0,0,0,0]]],kind="passive"))
        self.assertEqual(r["status"],"replaced")
        self.assertEqual(r["components"][0]["semantic"]["parameters"][0],4)
        self.assertEqual(r["native"]["effects"][0]["set"]["ParamList"][0],5)

    def test_player_description_uses_converted_values(self):
        r = self.c.convert(source([[0,3,3,[100,0,0,0,3,1]]]))
        description = TableWriter.description(r)
        self.assertIn("20%",description)
        self.assertNotIn("normalized",description)
        self.assertNotIn("FFBE",description)

    def test_zero_heal_does_not_gain_a_minimum_heal(self):
        r = self.c.convert(source([[1,2,2,[0,0,0,0]]]))
        self.assertEqual(r["status"],"noop")
        self.assertFalse(r["native"])

    def test_native_patch_has_patcher_required_roots_and_asset_paths(self):
        writer = TableWriter(self.c.native)
        writer.add(self.c.convert(source([[1,2,4,[50]]])))
        patch = writer.patch(ROOT/"build/abilities/fixture")
        self.assertIsInstance(patch["tables"],list)
        self.assertTrue(all(t["asset"].startswith("FFRS/Content/Datatable/") for t in patch["tables"]))

    def test_graph_resolves_region_and_reports_cycle_missing(self):
        graph = SkillGraph()
        for sid, child in (("1",2),("2",1),("3",999)):
            graph.add(self.c.convert(source([[0,3,71,[child,0]]],sid=sid)))
        resolved = graph.resolve()
        self.assertEqual(len(resolved["missing"]),1)
        self.assertEqual(len(resolved["cycles"]),1)


if __name__ == "__main__":
    unittest.main()
