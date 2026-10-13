"""Reference-scoped LB prelude keeps audio, charge CGS, and action clocks apart."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/ffbe2ss6")]
import ffbe_audio
import ffbe_resonance as resonance
import ffbe_frames
from build_sprites import BATTLE_ANIMS, Sheets, build
from PIL import Image


OPENING = {"durationFrames": 42, "chargeFrame": 24, "chargeMotion": "LB1_charge"}


class OpeningTests(unittest.TestCase):
    def test_all_lb_phases_select_the_vision_independently_of_the_shell(self):
        # The event-only shell defaults to both sides and an ordinary actor.
        # Every authored motion must override those defaults, including the
        # two dualcast branches and the looping cleanup pose.
        for source, expected in [({}, ["LB1_before", "LB1", "idle"]),
                                 ({"opening": OPENING, "moveType": 1},
                                  ["command", "LB1_charge", "LB1", "idle"])]:
            with self.subTest(source=source):
                plan = resonance.schedule(313/60, 1, 444040, source)
                motions = [e["set"] for e in plan["events"]
                           if e["set"]["EventType"] == "UnitPlayAnimByName"]
                self.assertEqual([e["Unit_PlayAnimByName_AnimationName"] for e in motions], expected)
                for event in motions:
                    name = event["Unit_PlayAnimByName_AnimationName"]
                    self.assertTrue(event["Unit_PlayAnimByName_IsOnlyVisionUnit"])
                    self.assertTrue(event["Unit_PlayAnimByName_IsPlayFriend"])
                    self.assertFalse(event["Unit_PlayAnimByName_IsPlayEnemy"])
                    self.assertFalse(event["Unit_PlayAnimByName_SkipDualcast"])
                    self.assertEqual(event["Unit_PlayAnimByName_AnimationID"], -1)
                    for side in ("First", "Second"):
                        self.assertEqual(event[f"Unit_PlayAnimByName_{side}DualcastAnimationName"], name)
                    self.assertEqual(event["Unit_PlayAnimByName_InLoopCount"], 0 if name == "idle" else 1)
                if source:
                    events = {e["set"]["EventType"]: e["set"] for e in plan["events"]}
                    self.assertTrue(events["UnitMoveToTarget"]["Unit_MoveToTarget_IsVisionUnit"])
                    self.assertTrue(events["UnitMoveToDefaultLocation"]["Unit_MoveToDefaultLocation_IsVision"])

    def test_source_clock_and_native_approach_charge_order(self):
        source = {"opening": OPENING, "moveType": 1, "hitFrames": [85, 283]}
        sounds = [{"frame": f, "bank": "test", "cueName": n, "durationMs": 250}
                  for f, n in [(-42, "opening"), (-18, "charge"), (12, "cosmo"), (90, "jump")]]
        plan = resonance.schedule(313/60, 2, 444040, source, sounds)
        anim = {e["set"].get("Unit_PlayAnimByName_AnimationName"): e["time"]
                for e in plan["events"] if e["set"]["EventType"] == "UnitPlayAnimByName"}
        audio = {e["set"]["Sound_PlayHitSound_playLabel"]: e["time"]
                 for e in plan["events"] if e["set"]["EventType"] == "SoundPlayHitSound"}
        self.assertEqual(anim["command"], 12000)
        self.assertEqual(anim["LB1_charge"], 21600)
        self.assertEqual(anim["LB1"], 28800)
        self.assertEqual(audio, {"opening": 12000, "charge": 21600, "cosmo": 33600, "jump": 64800})
        move = next(e for e in plan["events"] if e["set"]["EventType"] == "UnitMoveToTarget")
        self.assertLessEqual(move["time"] + move["set"]["Unit_MoveToTarget_Frame"] * 400, anim["LB1_charge"])
        hits = [e["time"] for e in plan["events"] if e["set"]["EventType"] == "OtherReaction"]
        self.assertEqual(hits, [28800 + 85 * 400, 28800 + 283 * 400])
        # The calibrated prelude is not inferred for another unit/ordinary LB.
        fallback = resonance.schedule(1, 1, 1)
        self.assertEqual(next(e["time"] for e in fallback["events"] if e["set"].get("Unit_PlayAnimByName_AnimationName") == "LB1"), 12000)

    def test_prepared_audio_has_two_distinct_prelude_cues_and_does_not_mutate_source(self):
        source = {"opening": deepcopy(OPENING), "sounds": [{"frame": 12, "cueId": 608}]}
        original = deepcopy(source)
        def bank(unit, skill, src, tbl):
            names = {608: "cosmo", 647: "se_slb_charge"}
            return {"name": "attack"}, [{**s, "sourceCueName": names[s["cueId"]]} for s in src["sounds"]]
        with patch.object(ffbe_audio, "_prepare_bank", side_effect=bank), patch.object(ffbe_audio, "system_bank", return_value=Path("System.json")), patch.object(ffbe_audio, "prepare_system_cue", return_value=({"name": "system"}, [{"sourceCueName": ffbe_audio.LB_OPENING_CUE, "frame": -42}])) as common:
            _, events = ffbe_audio.prepare({"key": "test"}, {"audio": "native"}, source, None)
            self.assertEqual([e["frame"] for e in events], [-42, -18, 12])
            self.assertEqual(events[1]["sourceCueName"], "se_slb_charge")
            self.assertEqual(common.call_args.args[4:6], (-42, "lb_opening"))
        self.assertEqual(source, original)

    def test_missing_requested_charge_audio_and_invalid_phase_fail(self):
        with patch.object(ffbe_audio, "_prepare_bank", return_value=({"name": "attack"}, [])):
            with self.assertRaisesRegex(ValueError, "missing.*charge sound"):
                ffbe_audio.prepare({}, {"audio": "native"}, {"opening": OPENING}, None)
        for opening in [{}, {"durationFrames": True}, {"durationFrames": 0}, {**OPENING, "chargeFrame": 42}, {**OPENING, "chargeMotion": "wrong"}]:
            with self.subTest(opening=opening), self.assertRaises(ValueError):
                resonance.schedule(1, 1, 1, {"opening": opening})

    def test_native_charge_alias_keeps_its_own_sixteen_frames(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as d:
            path = Path(d)
            Image.new("RGBA", (1, 1), "white").save(path / "unit_anime_123.png")
            (path / "unit_cgg_123.csv").write_text("", encoding="utf8")
            (path / "unit_super_limit_atk_before_cgs_123.csv").write_text("49,0,0,2,\n50,0,0,14,\n", encoding="utf8")
            _, _, anims = ffbe_frames.load_unit(path, "123")
            self.assertEqual(sum(s["delay"] for s in anims["super_limitatk_before"]), 16)
        main = (None, None, {"idle": [{"frame": 1, "x": 0, "y": 0, "delay": 8}],
                             "super_limitatk_before": anims["super_limitatk_before"]})
        with patch.object(Sheets, "compose", return_value=Image.new("RGBA", (4, 4), "white")):
            _, spec = build(Sheets(main), BATTLE_ANIMS, "test", 128)
        charge = next(a for a in spec["animations"] if a["name"] == "LB1_charge")
        self.assertEqual(charge["frameCount"], 16)
        self.assertEqual(charge["parts"]["part_0"]["Cell"], [[0, "test_49"], [2, "test_50"]])


if __name__ == "__main__":
    unittest.main()
