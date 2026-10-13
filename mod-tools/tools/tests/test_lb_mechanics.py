"""Regression cases for source targeting, normalization and elemental defaults."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ffbe_audio
import ffbe_lb as lb
import ffbe_resonance as resonance


def source_row(element="1,0,0,0,0,0,0,0", target="1@2@1", ranges="1@2@1"):
    return {"lb_id": "7", "name": "Example", "effect_type": "33@54@1", "move_type": "1", "wait": "0",
            "target": target, "target_range": ranges, "element_inflict": element,
            "effect_param": "-130,0,0,0,0,0,0,0,1,5@3,5,0@0,0,0,0,0,0,93000,0",
            "attack_frames": "90:100:2:2@90:100:2:2@30:20:2:2-60:30:2:2-90:50:2:2"}


class MechanicsTests(unittest.TestCase):
    def source(self, **kwargs):
        with patch.object(lb, "table", return_value={"rows": [], "file": "fixture"}):
            return lb.from_master("123", {"MoveOffset": "65:0,40:25", "MoveSpeed": "5"}, source_row(**kwargs), ["7", "8"])

    def test_damage_component_target_and_cloud_total_are_independent_of_buffs(self):
        source = self.source()
        cloud = lb.cloud_reference()
        p = lb.profile(source, cloud)
        self.assertTrue(p["supported"])
        s = p["set"]
        self.assertEqual((s["TargetType"], s["defaultTargetRelation"], s["hitCount"]), ("Single", "Enemies", 3))
        self.assertEqual(s["element"], "Fire")
        self.assertEqual(s["effectBundleList"], cloud["effectBundleList"])
        self.assertAlmostEqual(sum(s["hitDamageRatioList"]), 1)
        self.assertAlmostEqual(sum(s["magnification"] * w for w in s["hitDamageRatioList"]), 36)
        self.assertEqual(p["sourceMultiplier"], 930)
        group = lb.profile(self.source(ranges="1@2@2"))
        self.assertEqual(group["set"]["TargetType"], "Group")

    def test_lb_second_offset_maps_to_ground_axes_and_keeps_clearance(self):
        source = self.source()
        self.assertEqual(source["movement"]["lbOffset"], [40, 25])
        self.assertEqual(source["movement"]["normalOffset"], [65, 0])
        plan = resonance.schedule(2, 3, 444010, source)
        move = next(e["set"] for e in plan["events"] if e["set"]["EventType"] == "UnitMoveToTarget")
        self.assertEqual(move["Unit_MoveToTarget_AddLocation"], {"x": -25, "y": 240, "z": 0})
        self.assertFalse(move["Unit_MoveToTarget_IsDisableOffset"])
        self.assertTrue(move["Unit_MoveToTarget_IsVisionUnit"])
        with self.assertRaises(ValueError): lb.move_offsets("65:0")

    def test_element_order_blend_and_custom_override(self):
        source = self.source(element="0,1,1,0,0,0,0,0")
        self.assertEqual(source["elements"], ["Ice", "Thunder"])
        self.assertEqual(lb.element_color(source["elements"]), "#80FF80")
        self.assertEqual(lb.element_color(["Ice", "Ice", "Thunder"]), "#80FF80")
        self.assertEqual(lb.element_color([]), "#808080")
        self.assertEqual(lb.element_color(["None"]), "#808080")
        self.assertEqual(resonance.resolved_field_color({"field_color": "#FFAA33"}, source), "#80FF80")
        self.assertEqual(resonance.resolved_field_color({"field_color_mode": "custom", "field_color": "#ab1234"}, source), "#AB1234")
        self.assertFalse(lb.profile(source)["supported"])
        self.assertTrue(any("one damage element" in s for s in lb.profile(source)["issues"]))
        self.assertEqual(self.source(element="0,0,0,1,0,0,0,0")["elements"], ["Water"])

    def test_sound_requires_explicit_experimental_opt_in(self):
        with patch.object(ffbe_audio, "bank_info", side_effect=AssertionError("bank must not load")):
            self.assertEqual(ffbe_audio.prepare({"key": "test"}, {"audio_bank": "missing.acb"}, {"sounds": [{"cueId": 1}]}, None), (None, []))

    def test_manifest_variant_change_does_not_return_stale_source(self):
        source = self.source()
        other = source_row(element="0,1,0,0,0,0,0,0"); other["lb_id"] = "8"
        tables = {"F_UNIT_MST": [{"unit_evo_id": "123", "lb_id": "7,8", "MoveOffset": "65:0,40:25"}],
                  "F_LIMITBURST_MST": [other], "F_EFFECT_GROUP_MST": []}
        with tempfile.TemporaryDirectory(prefix="lb-profile-", dir=ROOT / "build") as temp:
            self.assertTrue(Path(temp).resolve().is_relative_to((ROOT / "build").resolve()))
            path = Path(temp, "source.json"); path.write_text(json.dumps(source), encoding="utf-8")
            with patch.object(lb, "table", side_effect=lambda n: {"rows": tables[n], "file": n}):
                result = lb.resolve({"ffbe": {"id": "123"}}, {"ffbe_lb": str(path), "ffbe_lb_id": "8"})
                self.assertEqual(result["elements"], ["Ice"])
                self.assertEqual(result["lbId"], "8")

    def test_unsupported_damage_does_not_silently_borrow_cloud_targeting(self):
        source = self.source(); source.pop("damageComponent")
        self.assertFalse(lb.profile(source)["supported"])
        self.assertNotIn("set", lb.profile(source))

    def test_more_than_thirty_hits_is_reviewable_in_studio(self):
        row = {**source_row(), "effect_type": "1", "attack_frames": "-".join(f"{i}:2" for i in range(50))}
        with patch.object(lb, "table", return_value={"rows": [], "file": "fixture"}):
            source = lb.from_master("123", {}, row, ["7"])
        self.assertFalse(lb.profile(source)["supported"])
        self.assertIn("at most 30 hits", lb.profile(source)["issues"][0])

    def test_gl_datamine_preserves_lightning_instead_of_using_jp_mechanics(self):
        forms = {"123": {"limitburst_id": [7]}}
        burst = {"name": "Example", "move_type": 4, "element_inflict": ["Lightning"],
                 "attack_frames": [[30]], "attack_damage": [[100]],
                 "levels": {"1": {"effects_raw": [[1, 1, 1, [0, 0, 0, 0, 0, 0, 300, 0]]]}}}
        with patch.object(lb, "datamine", return_value=(forms, {"7": burst}, "gl-fixture")), \
                patch.object(lb, "table", return_value={"rows": [], "file": "unused"}):
            source = lb.resolve({"ffbe": {"id": "123", "source": "GLW"}}, {})
        self.assertEqual(source["elements"], ["Thunder"])
        self.assertEqual(lb.profile(source)["set"]["element"], "Thunder")
        self.assertEqual(source["hitFrames"], [30])
        self.assertIsNone(source["movement"]["lbOffset"])
        self.assertTrue(source["warnings"])

    def test_gl_nested_effects_keep_damage_and_only_match_verified_presentation(self):
        forms = {"123": {"limitburst_id": [7]}}
        burst = {"name": "Example", "move_type": 1, "element_inflict": ["Lightning"],
                 "attack_frames": [[30], [30]], "attack_damage": [[100], [100]],
                 "levels": {"1": {"effects_raw": [[1, 1, 1, [0, 0, 0, 0, 0, 0, 300, 0]],
                                                   [1, 1, 100, [[916002, 916003], 1]]]}}}
        jp = {"lb_id": "7", "effect_type": "1", "move_type": "1", "attack_frames": "30:100",
              "target": "1", "target_range": "1", "effect_param": "0,0,0,0,0,0,99999,0",
              "effect_frames": "0:55:1:4:0@100:55:1:7:0", "element_inflict": "1,0,0,0,0,0,0,0"}
        tables = {"F_UNIT_MST": [{"unit_evo_id": "123", "lb_id": "7", "MoveOffset": "65:0,40:25"}],
                  "F_LIMITBURST_MST": [jp], "F_EFFECT_GROUP_MST": [{"qIy86WvJ": "55", "1fVZ3rKd": "20:1"}]}
        with patch.object(lb, "datamine", return_value=(forms, {"7": burst}, "gl-fixture")), \
                patch.object(lb, "table", side_effect=lambda n: {"rows": tables[n], "file": n}):
            unit = {"ffbe": {"id": "123", "source": "GLW"}}
            source = lb.resolve(unit, {})
            self.assertEqual(source["components"][1]["params"], [[916002, 916003], 1])
            self.assertEqual(lb.profile(source)["set"]["element"], "Thunder")
            self.assertEqual(lb.profile(source)["sourceMultiplier"], 3)
            self.assertEqual(source["movement"]["lbOffset"], [40, 25])
            self.assertEqual([(s["frame"], s["cueId"]) for s in source["sounds"]], [(20, 1)])
            self.assertTrue(any("Conditional" in w for w in source["warnings"]))
            jp["attack_frames"] = "60:100"
            unmatched = lb.resolve(unit, {})
            self.assertEqual(unmatched["sounds"], [])
            self.assertIsNone(unmatched["movement"]["lbOffset"])


class ParserTests(unittest.TestCase):
    def parse(self, row):
        with patch.object(lb, "table", return_value={"rows": [], "file": "fixture"}):
            return lb.from_master("123", {}, row, ["7"])

    def test_shared_timing_keeps_the_damage_component_target_and_weights(self):
        # A shared sequence also occurs when the damage follows ally buffs.
        for types, target, ranges, index in (("1@3", "1@2", "1@2", 0),
                                             ("3@15", "2@1", "2@2", 1)):
            with self.subTest(types=types):
                row = {**source_row(), "effect_type": types, "target": target, "target_range": ranges,
                       "attack_frames": "30:20:3:2-60:30:3:2-90:50:3:2"}
                parsed = self.parse(row)
                self.assertEqual(parsed["damageComponent"], index)
                self.assertEqual(parsed["hitFrames"], [30, 60, 90])
                self.assertEqual(parsed["hitPercents"], [20, 30, 50])
                profile = lb.profile(parsed)
                self.assertTrue(profile["supported"])
                self.assertEqual(profile["set"]["defaultTargetRelation"], "Enemies")
                self.assertEqual(profile["set"]["TargetType"], "Single" if index == 0 else "Group")
                self.assertAlmostEqual(sum(profile["set"]["hitDamageRatioList"]), 1)

    def test_partial_multiple_timing_groups_remain_unresolved(self):
        row = {**source_row(), "attack_frames": "30:100@60:100"}
        self.assertIsNone(lb.damage_timing(row))
        self.assertFalse(lb.profile(self.parse(row))["supported"])
        # One shared sequence cannot choose between two damage components.
        self.assertIsNone(lb.damage_timing({**row, "effect_type": "1@15", "attack_frames": "30:100"}))

    def test_missing_or_invalid_shared_weights_are_not_silently_repaired(self):
        for frames in ("30", "30:50", "60:50-30:50", "30:-5-60:105"):
            with self.subTest(frames=frames), self.assertRaises(ValueError):
                lb.damage_timing({**source_row(), "attack_frames": frames})
        self.assertIsNone(lb.damage_timing({**source_row(), "attack_frames": ""}))
        self.assertIsNone(lb.damage_timing({**source_row(), "attack_frames": "-".join(f"{i}:2" for i in range(50))}))

    def test_jp_compound_parameters_preserve_tokens_and_positions(self):
        row = {**source_row(), "effect_type": "1@100@124@60", "target": "1@3@1@1", "target_range": "2@0@2@2",
               "effect_param": "0,0,0,0,0,0,3260,0@2&2,511175&511176,,4@0,0,50:50@2,20,うっふん",
               "attack_frames": "30:100"}
        parsed = self.parse(row)
        self.assertEqual(parsed["components"][0]["multiplier"], 32.6)
        self.assertEqual(parsed["components"][1]["params"], ["2&2", "511175&511176", "", 4])
        self.assertEqual(parsed["components"][2]["params"], [0, 0, "50:50"])
        self.assertEqual(parsed["components"][3]["params"], [2, 20, "うっふん"])
        self.assertEqual(parsed["rawLb"]["effect_param"], row["effect_param"])

    def test_empty_sound_reference_is_reported_and_other_cues_survive(self):
        tables = {"F_EFFECT_GROUP_MST": [{"qIy86WvJ": "5035929", "1fVZ3rKd": "1:57:1,1:,20:0"}]}
        with patch.object(lb, "table", side_effect=lambda name: {"rows": tables.get(name, [])}):
            result = lb.presentation({}, {"effect_frames": "10:5035929"})
        self.assertEqual([(s["frame"], s["cueId"]) for s in result["sounds"]], [(11, 57), (30, 0)])
        self.assertTrue(any("Missing sound cue ID" in w and "5035929" in w for w in result["warnings"]))

    def test_gl_shared_sequence_and_nested_params_keep_regional_mechanics(self):
        burst = {"move_type": 1, "element_inflict": ["Lightning"], "attack_frames": [[30, 60]],
                 "attack_damage": [[25, 75]], "levels": {"1": {"effects_raw": [
                     [2, 1, 1, [0, 0, 0, 0, 0, 0, 300, 0]], [0, 3, 100, [[7, 8], 1]]]}}}
        with patch.object(lb, "datamine", return_value=({"123": {"limitburst_id": [7]}}, {"7": burst}, "gl-fixture")), \
                patch.object(lb, "table", return_value={"rows": [], "file": "unused"}):
            parsed = lb.from_datamine({"ffbe": {"id": "123", "source": "GL"}}, {})
            self.assertEqual(parsed["hitFrames"], [30, 60])
            self.assertEqual(parsed["hitPercents"], [25, 75])
            self.assertEqual(lb.profile(parsed)["set"]["element"], "Thunder")
            parsed["components"][1]["params"][0].append(9)
            self.assertEqual(burst["levels"]["1"]["effects_raw"][1][3], [[7, 8], 1])
            burst["attack_damage"] = [[100]]
            with self.assertRaisesRegex(ValueError, "different lengths"):
                lb.from_datamine({"ffbe": {"id": "123", "source": "GL"}}, {})


if __name__ == "__main__":
    unittest.main()
