"""LB effect components, vision movement and embedded CRI audio regressions."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ffbe_audio
from ffbe_effects import acb_routing
from ffbe_effects.acb_cues import utf
import ffbe_lb
import ffbe_resonance as resonance
import make_vision_mod as generator
import test_ffbe_resonance as cooked_tests
from test_ffbe_resonance import number


class SourceTests(unittest.TestCase):
    def test_debuff_components_do_not_add_damage_hits(self):
        result = ffbe_lb.damage_timing({"lb_id": "1", "effect_type": "33@24@1",
                                       "attack_frames": "90:100:2:2@90:100:2:2@30:20:2:2-60:30:2:2-90:50:2:2"})
        self.assertEqual(result, {"damageComponent": 2, "hitFrames": [30, 60, 90], "hitPercents": [20, 30, 50]})
        self.assertIsNone(ffbe_lb.damage_timing({"effect_type": "1@15", "attack_frames": "1:100@2:100"}))
        with self.assertRaises(ValueError):
            ffbe_lb.damage_timing({"lb_id": "1", "effect_type": "1", "attack_frames": "10:50"})

    def test_form_selects_first_lb_variant_and_rejects_unrelated_lb(self):
        tables = {"F_UNIT_MST": [{"unit_evo_id": "123", "lb_id": "7,8,9"}],
                  "F_LIMITBURST_MST": [{"lb_id": "7", "move_type": "1", "effect_type": "1", "attack_frames": "30:100"}],
                  "F_EFFECT_GROUP_MST": []}
        with patch.object(ffbe_lb, "table", side_effect=lambda name: {"rows": tables[name], "file": name}):
            data = ffbe_lb.resolve({"ffbe": {"id": "123"}}, {})
            self.assertEqual(data["lbId"], "7")
            self.assertEqual(data["hitFrames"], [30])
            self.assertEqual(data["moveType"], 1)
            with self.assertRaises(ValueError):
                ffbe_lb.resolve({"ffbe": {"id": "123"}}, {"ffbe_lb_id": 10})

    def test_stationary_lb_and_audio_tail(self):
        source = {"moveType": 0, "hitFrames": [1]}
        sound = {"frame": 40, "cueName": "example", "bank": "test", "durationMs": 3000}
        plan = resonance.schedule(0.2, 1, 444010, source, [sound])
        kinds = [e["set"]["EventType"] for e in plan["events"]]
        self.assertNotIn("UnitMoveToTarget", kinds)
        self.assertGreater(plan["duration"], 12000 + 40 * 400 + 3 * 24000)

    def test_explicit_target_offset_is_preserved(self):
        plan = resonance.schedule(1, 1, 444010, {"moveType": 1}, movement={"target_offset": [-160, 20, 0]})
        move = next(e["set"] for e in plan["events"] if e["set"]["EventType"] == "UnitMoveToTarget")
        self.assertEqual(move["Unit_MoveToTarget_AddLocation"], {"x": -160, "y": 20, "z": 0})

    def test_routing_keeps_main_output_and_non_routing_commands(self):
        cmd = b"\x00\x6f\x04\x00\x00\x27\x10\x00\x6f\x04\x00\x01\x27\x10\x00\x79\x02\x00\x96"
        self.assertEqual(acb_routing.route_commands(cmd, ["MasterOut", "BUS1"]), cmd[:7] + cmd[14:])
        with self.assertRaises(ValueError):
            acb_routing.route_commands(cmd[:-1], ["MasterOut", "BUS1"])


class SourceAssetTests(unittest.TestCase):
    run_dt = staticmethod(cooked_tests.CookedResonanceTests.run_dt)
    dump = classmethod(cooked_tests.CookedResonanceTests.dump.__func__)

    @classmethod
    def setUpClass(cls):
        shell = Path(generator.LEGACY, resonance.SHELL + ".uasset")
        bank_shell = Path(generator.LEGACY, ffbe_audio.SHELL + ".uasset")
        acb = Path("S:/FFBE JP Data Export/public/SE.acb")
        if not all(p.exists() for p in (shell, bank_shell, acb)):
            raise unittest.SkipTest("Extract the event shell and CRI bank, and supply FFBE SE.acb")
        cls.temp = tempfile.TemporaryDirectory(prefix="lb-source-", dir=ROOT / "build")
        cls.work = Path(cls.temp.name).resolve()
        assert cls.work.is_relative_to((ROOT / "build").resolve())
        cls.addClassCleanup(cls.temp.cleanup)
        out = cls.work / "assets"
        tables, clones, jobs = {}, [], []
        def tbl(rel):
            return tables.setdefault(rel, {"asset": generator.DT + rel, "add": [], "set": []})
        source = {"lbId": "test", "moveType": 1, "hitFrames": [30, 36, 42], "hitPercents": [10, 20, 70],
                  "movement": {"ffrTargetOffset": [-25, 40, 0]},
                  "sounds": [{"frame": 6, "cueId": 647}, {"frame": 50, "cueId": 1}]}
        skill = {"jp": "SourceTest", "from": 440110, "audio_bank": str(acb), "audio": "experimental", "mechanics": "custom"}
        donor = generator.row_by("Skill/DT_SkillData", "ID", 440110)[0]
        tbl("Skill/DT_SkillData")["add"].append({"row": "SourceTest", "cloneFrom": donor, "set": {"ID": 444010}})
        with patch.object(generator, "lb_motion_seconds", return_value=4.2), patch.object(ffbe_lb, "resolve", return_value=source):
            generator.prepare_ffbe_resonance({"key": "source", "ffbe": {"id": "123"}}, skill, 444010, tbl, clones, jobs)
        p = cls.work / "patch.json"
        p.write_text(json.dumps({"legacyRoot": generator.LEGACY, "outRoot": str(out),
                                 "tables": list(tables.values()), "clones": clones}), encoding="utf-8")
        cls.run_dt([*generator.FFRDT, "patch", str(p), "--usmap", generator.USMAP])
        job = jobs[0]
        resonance.build(job, out, cls.work, generator.FFRDT, generator.USMAP, cls.run_dt)
        ffbe_audio.build(job["audio"], out, cls.work, generator.FFRDT, generator.USMAP, cls.run_dt, generator.LEGACY)
        path = out / (job["asset"] + ".uasset")
        cls.asset = cls.dump(path, "tojson")
        cls.functions = cls.dump(path, "seqdump")
        cls.bank_path = out / (job["audio"]["asset"] + ".uasset")
        cls.bank = cls.dump(cls.bank_path, "tojson")
        cls.original_acb = acb.read_bytes()
        cls.skills = cls.dump(out / (generator.DT + "Skill/DT_SkillData.uasset"), "rows")["rows"]
        cls.sound_rows = cls.dump(out / (generator.DT + "Asset/Sound/DT_SoundCueSheetAsset.uasset"), "rows")["rows"]
        cls.plan = job["plan"]
        cls.bank_name = job["audio"]["name"]

    def test_vision_flags_hit_ticks_and_cue_strings_survive_cooking(self):
        self.assets = [(self.asset, self.functions, self.plan)]
        cooked_tests.CookedResonanceTests.test_cooked_schedule_matches_channel(self)
        functions = {int(k.split(":")[0]): v for k, v in self.functions.items()}
        events = []
        for e in self.asset["Exports"]:
            for p in e.get("Data", []):
                if p["Name"] == "EventChannel":
                    for t, v in zip(resonance.child(p["Value"], "KeyTimes"), resonance.child(p["Value"], "KeyValues")):
                        events.append((number(t), functions[resonance.child(v["Value"], "Ptrs", "Function")]))
        self.assertEqual([t for t, e in events if e["EventType"] == "OtherReaction"], [24000, 26400, 28800])
        move = next(e for _, e in events if e["EventType"] == "UnitMoveToTarget")
        self.assertTrue(move["Unit_MoveToTarget_IsVisionUnit"])
        # seqdump omits false/default event arguments.
        self.assertFalse(move.get("Unit_MoveToTarget_IsDisableOffset", False))
        self.assertEqual(move["Unit_MoveToTarget_AddLocation"], {"x": -25.0, "y": 240.0, "z": 0.0})
        back = next(e for _, e in events if e["EventType"] == "UnitMoveToDefaultLocation")
        self.assertTrue(back["Unit_MoveToDefaultLocation_IsVision"])
        sounds = [(t, e["Sound_PlayHitSound_playLabel"], e["Sound_PlayHitSound_CueSheetName"])
                  for t, e in events if e["EventType"] == "SoundPlayHitSound"]
        self.assertEqual(sounds, [(14400, "se_slb_charge", self.bank_name), (32000, "se_attack_sword_slash_1", self.bank_name)])
        row = self.skills["SourceTest"]
        self.assertEqual(row["hitCount"], 3)
        for actual, expected in zip(row["hitDamageRatioList"], [0.1, 0.2, 0.7] + [0] * 27):
            self.assertAlmostEqual(actual, expected)

    def test_complete_acb_is_embedded_and_registered(self):
        export = self.bank["Exports"][0]
        payload = base64.b64decode(export["Extras"])
        self.assertEqual(payload[:4], bytes(4))
        routed_acb = acb_routing.adapt(self.original_acb)
        self.assertEqual(payload[4:], routed_acb)
        self.assertEqual(struct.unpack_from(">I", payload, 8)[0] + 8, len(self.original_acb))
        self.assertTrue(self.sound_rows[self.bank_name]["pCueSheet"].endswith("/" + self.bank_name))
        cues = resonance.child(self.bank["Exports"][0]["Data"], "CueInfos")
        names = [resonance.child(c["Value"], "Name") for c in cues]
        self.assertIn("se_slb_charge", names)
        self.assertIn("se_attack_sword_all_slash_1", names)
        # Unreal consumes DataResources, not the ACB header checked above. A
        # stale donor resource crashed FAsyncLoadingThread before the main menu.
        resource = self.bank["DataResources"][0]
        self.assertEqual(resource["SerialOffset"], export["SerialSize"] - len(payload) + 4)
        self.assertEqual(resource["SerialSize"], len(self.original_acb))
        self.assertEqual(resource["RawSize"], len(self.original_acb))
        raw_export = self.bank_path.with_suffix(".uexp").read_bytes()
        start, size = resource["SerialOffset"], resource["SerialSize"]
        self.assertLessEqual(start + size, export["SerialSize"])
        self.assertEqual(raw_export[start:start + size], routed_acb)
        self.run_dt([*generator.FFRDT, "check-atom-bank", str(self.bank_path), "--usmap", generator.USMAP])

    def test_routing_preserves_samples_and_cue_graphs(self):
        original = utf(self.original_acb)[1][0]
        routed = utf(base64.b64decode(self.bank["Exports"][0]["Extras"])[4:])[1][0]
        changed = {key for key in original if original[key] != routed[key]}
        self.assertEqual(changed, {"AcfReferenceTable", "SeqCommandTable", "TrackCommandTable", "SynthCommandTable"})
        # Includes every encoded sample, cue name, ID, graph link and duration.
        self.assertEqual(original["AwbFile"], routed["AwbFile"])
        refs = utf(routed["AcfReferenceTable"])[1]
        self.assertEqual([(r["Type"], r["Name"], r["Id"]) for r in refs], [(3, "SE", 3), (9, "MasterOut", 0xffffffff)])
        strings = [r["StringValue"] for r in utf(routed["StringValueTable"])[1]]
        for table in ("SeqCommandTable", "TrackCommandTable", "SynthCommandTable"):
            before, after = utf(original[table])[1], utf(routed[table])[1]
            self.assertEqual(len(before), len(after))
            for old, new in zip(before, after):
                old_cmds = list(acb_routing.commands(old["Command"]))
                new_cmds = list(acb_routing.commands(new["Command"]))
                self.assertEqual([c for c in old_cmds if c[0] not in (0x41, 0x6f)],
                                 [c for c in new_cmds if c[0] not in (0x41, 0x6f)])
                for op, args in new_cmds:
                    if op == 0x6f:
                        self.assertEqual(strings[struct.unpack_from(">H", args)[0]], "MasterOut")
                    if op == 0x41:
                        self.assertEqual(args, struct.pack(">I", 3))

    def test_bulk_checker_rejects_stale_loading_metadata(self):
        for field in ("SerialOffset", "SerialSize", "RawSize"):
            with self.subTest(field=field):
                bad = deepcopy(self.bank)
                bad["DataResources"][0][field] += 1
                path = self.work / "bad-bank.json"
                path.write_text(json.dumps(bad), encoding="utf-8")
                asset_path = self.work / "bad-bank.uasset"
                self.run_dt([*generator.FFRDT, "fromjson", str(path), str(asset_path), "--usmap", generator.USMAP])
                result = subprocess.run([*generator.FFRDT, "check-atom-bank", str(asset_path), "--usmap", generator.USMAP],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertIn("bulk metadata mismatch", result.stderr)
