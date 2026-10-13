"""Validate authored cooked assets, including the schedule Unreal actually loads."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ffbe_resonance as resonance
import make_vision_mod as generator


def number(p):
    while not isinstance(p, (int, float)):
        p = p[0] if isinstance(p, list) else p["Value"]
    return p


class SettingsTests(unittest.TestCase):
    def test_cg_imports_are_migrated_and_direct_builds_use_own_lb(self):
        for donor in resonance.CG_TEMPLATES:
            original = {"ffbe": {"id": "123"}, "en": "Saved vision", "lb_custom": {
                "from": 440110, "visuals": donor, "presentation": "template", "field_color": "#123456"}}
            updated = resonance.migrate_cg(original)
            self.assertEqual(updated["lb_custom"]["presentation"], "ffbe")
            self.assertEqual(updated["lb_custom"]["field_color"], "#123456")
            self.assertEqual(original["lb_custom"]["presentation"], "template")
            self.assertTrue(resonance.uses_ffbe(original, {**original["lb_custom"], "resonance": True}))
            self.assertIs(resonance.migrate_cg(updated), updated)
        safe = {"ffbe": {"id": "123"}, "lb_custom": {"from": 440110, "visuals": 414090, "presentation": "template"}}
        self.assertIs(resonance.migrate_cg(safe), safe)
        self.assertFalse(resonance.uses_ffbe(safe, {**safe["lb_custom"], "resonance": True}))

    def test_motion_duration_uses_the_sprite_players_minimum_delay(self):
        with tempfile.TemporaryDirectory(prefix="lb-duration-", dir=ROOT / "build") as work:
            self.assertTrue(Path(work).resolve().is_relative_to((ROOT / "build").resolve()))
            Path(work, "unit_limitatk_cgs_123.csv").write_text("0,0,0,0\n1,0,0,-1\n2,0,0,60\n", encoding="utf-8")
            self.assertAlmostEqual(generator.lb_motion_seconds({"ffbe": {"dir": work, "id": "123"}}), 62 / 60)

    def test_default_and_explicit_template(self):
        self.assertTrue(resonance.uses_ffbe({"ffbe": {}}, {"resonance": True, "presentation": "ffbe"}))
        self.assertTrue(resonance.uses_ffbe({"ffbe": {"id": "123"}}, {"resonance": True}))
        self.assertFalse(resonance.uses_ffbe({"ffbe": {"id": "123"}}, {"resonance": True, "presentation": "template"}))
        self.assertFalse(resonance.uses_ffbe({"ffbe": {"id": "123"}}, {}))

    def test_invalid_settings_fail_before_build(self):
        for color in ("red", "#fff", "#1234567", "#GG0000", 123):
            with self.subTest(color=color), self.assertRaises(ValueError):
                resonance.field_color(color)
        for seconds in (None, 0, -1, float("nan"), float("inf")):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                resonance.schedule(seconds, 10, 444010)
        self.assertEqual(resonance.field_color("#aa44cc"), "#AA44CC")


class CookedResonanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path(generator.LEGACY, resonance.SHELL + ".uasset").exists():
            raise unittest.SkipTest("Extract Cloud's event-only Cut sequence first")
        cls.temp = tempfile.TemporaryDirectory(prefix="ffbe-resonance-", dir=ROOT / "build")
        cls.work = Path(cls.temp.name).resolve()
        assert cls.work.is_relative_to((ROOT / "build").resolve())
        cls.addClassCleanup(cls.temp.cleanup)
        cls.out = cls.work / "assets"
        cls.tables, clones, jobs = {}, [], []
        def tbl(rel):
            return cls.tables.setdefault(rel, {"asset": generator.DT + rel, "add": [], "set": []})
        cls.plans = {}
        for vid, duration, color, donor in ((13500, 0.2, "#FFAA33", 440110), (13501, 24.75, "#5588FF", 414100)):
            unit = {"id": vid, "key": f"test{vid}", "donor": 13125, "ffbe": {"id": "123"}}
            skill = {"jp": f"Test{vid}_LB", "from": donor, "field_color": color,
                     "field_color_mode": "custom", "mechanics": "custom"}
            with patch.object(generator, "lb_motion_seconds", return_value=duration):
                generator.prepare_ffbe_resonance(unit, skill, generator.lb_id(vid), tbl, clones, jobs)
        p = cls.work / "patch.json"
        p.write_text(json.dumps({"legacyRoot": generator.LEGACY, "outRoot": str(cls.out),
                                 "tables": list(cls.tables.values()), "clones": clones}), encoding="utf-8")
        cls.run_dt([*generator.FFRDT, "patch", str(p), "--usmap", generator.USMAP])
        cls.assets = []
        for job in jobs:
            resonance.build(job, cls.out, cls.work, generator.FFRDT, generator.USMAP, cls.run_dt)
            pkg = cls.out / (job["asset"] + ".uasset")
            asset = cls.dump(pkg, "tojson")
            events = cls.dump(pkg, "seqdump")
            cls.assets.append((asset, events, job["plan"]))
        cls.grading = cls.dump(cls.out / "FFRS/Content/Datatable/PostProcess/DT_ColorGradingParameter.uasset", "rows")["rows"]
        cls.original_grading = cls.dump(Path(generator.LEGACY) / "FFRS/Content/Datatable/PostProcess/DT_ColorGradingParameter.uasset", "rows")["rows"]
        cls.skill_assets = cls.dump(cls.out / "FFRS/Content/Datatable/Asset/Skill/DT_SkillAsset.uasset", "rows")["rows"]

    @staticmethod
    def run_dt(command):
        r = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)

    @classmethod
    def dump(cls, path, verb):
        out = cls.work / "check.json"
        cls.run_dt([*generator.FFRDT, verb, str(path), str(out), "--usmap", generator.USMAP])
        return json.loads(out.read_text(encoding="utf-8-sig"))

    def test_cooked_schedule_matches_channel(self):
        for asset, _, plan in self.assets:
            exps = asset["Exports"]
            active = [(i, p) for i, e in enumerate(exps, 1) for p in e.get("Data", [])
                      if p.get("Name") == "EventChannel" and resonance.child(p["Value"], "KeyTimes")]
            self.assertEqual(len(active), 1)
            section_id, channel = active[0]
            times = [number(t) for t in resonance.child(channel["Value"], "KeyTimes")]
            self.assertEqual(times, [e["time"] for e in plan["events"]])
            self.assertEqual(len(resonance.child(channel["Value"], "KeyValues")), len(times))
            compiled = next(e for e in exps if e["ObjectName"] == "CompiledData")
            field = resonance.child(compiled["Data"], "EntityComponentField")
            entities = resonance.child(field, "Entities")
            self.assertEqual(len(entities), len(times))
            for i, entity in enumerate(entities):
                self.assertEqual(resonance.child(entity["Value"], "Key", "EntityOwner"), section_id)
                self.assertEqual(resonance.child(entity["Value"], "Key", "EntityID"), i)
            tree = resonance.child(field, "OneShotEntityTree")[0]["Value"]["SerializedData"]
            cooked = []
            for node in tree["ChildNodes"]["Items"]:
                entry = tree["Data"]["Entries"][node["DataID"]["EntryIndex"]]
                for item in tree["Data"]["Items"][entry["StartIndex"]:entry["StartIndex"] + entry["Size"]]:
                    cooked.append((number(node["Range"]["LowerBound"]["Value"]), item["EntityIndex"]))
            self.assertEqual(cooked, list(zip(times, range(len(times)))))

    def test_motion_cleanup_and_hits_survive_asset_roundtrip(self):
        for asset, functions, plan in self.assets:
            fn = {int(k.split(":")[0]): v for k, v in functions.items()}
            events = []
            for e in asset["Exports"]:
                for p in e.get("Data", []):
                    if p.get("Name") != "EventChannel":
                        continue
                    times = resonance.child(p["Value"], "KeyTimes")
                    values = resonance.child(p["Value"], "KeyValues")
                    for t, v in zip(times, values):
                        ptrs = resonance.child(v["Value"], "Ptrs")
                        fid = resonance.child(ptrs, "Function")
                        self.assertEqual(resonance.child(ptrs, "BoundObjectProperty")["ResolvedOwner"], fid)
                        events.append((number(t), fn[fid]))
            for (_, actual), expected in zip(events, plan["events"]):
                for key, value in expected["set"].items():
                    # seqdump omits zero/false values.
                    self.assertEqual(actual.get(key, 0), value)
            motions = [(t, e.get("Unit_PlayAnimByName_AnimationName")) for t, e in events if e["EventType"] == "UnitPlayAnimByName"]
            self.assertEqual([m for _, m in motions], ["LB1_before", "LB1", "idle"])
            self.assertEqual(events[-1][1]["EventType"], "PostSetDefaultColorGrading")
            self.assertLess(events[-1][0], plan["duration"])
            self.assertFalse(any(e["EventType"] in ("OtherSkipResetParameter", "OtherTalkPlay", "BGChange") for _, e in events))
            scene = next(e for e in asset["Exports"] if e["ObjectName"] == "MovieScene_0")
            bounds = resonance.child(scene["Data"], "PlaybackRange")[0]["Value"]
            self.assertEqual(number(bounds["UpperBound"]["Value"]), plan["duration"])

    def test_no_movie_or_sound_dependencies(self):
        for asset, _, _ in self.assets:
            names = [i["ObjectName"] for i in asset["Imports"]]
            self.assertFalse(any("Mana" in n or "Sound_001" in n or "SoundAtomCue" in n for n in names))
        for sid in (444011, 444012, 444021, 444022):
            row = next(r for r in self.skill_assets.values() if r["ID"] == sid)
            self.assertEqual(row["soundSequence"], "None")
            self.assertTrue(row["LevelSequence"].endswith("_Master"))

    def test_field_color_roundtrip_preserves_all_four_components(self):
        warm = self.grading["FFBE_Field_444010"]["colorGainGlobal"]["colorGainGlobal"]
        cool = self.grading["FFBE_Field_444020"]["colorGainGlobal"]["colorGainGlobal"]
        for key, value in zip("XYZW", (1.0, 0.8, 0.52, 1.0)):
            self.assertAlmostEqual(warm[key], value, places=5)
        self.assertGreater(cool["Z"], cool["X"])
        # Private rows leave Cloud and other native skills unchanged.
        for name, row in self.original_grading.items():
            self.assertEqual(self.grading[name], row)
