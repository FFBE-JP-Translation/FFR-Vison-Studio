"""Regression checks against Cloud's extracted sequence; never writes to the game.

Build ffr-dt, then run: python -B -m unittest discover -s tools/tests -v
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch as mock_patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import make_vision_mod as generator

DLL = ROOT / "src/ffr-dt/bin/Release/net8.0/ffr-dt.dll"
USMAP = ROOT / "extracted/Mappings.usmap"
DONOR = ROOT / "extracted/legacy/FFRS/Content/Sequencer/Battle/Skill/440110/440111"


def prop(obj, name):
    return next((p for p in obj.get("Data", []) if isinstance(p, dict) and p.get("Name") == name), None)


def number(value):
    while not isinstance(value, (int, float)):
        value = value[0] if isinstance(value, list) else value["Value"]
    return value


def section_range(export):
    value = prop(export, "SectionRange")
    if value is None:
        return None
    while "LowerBound" not in value:
        value = value[0] if isinstance(value, list) else value["Value"]
    return value


def channels(value):
    if isinstance(value, dict):
        if value.get("StructType") == "MovieSceneEventChannel":
            fields = {p["Name"]: p for p in value["Value"]}
            times = fields.get("KeyTimes", fields.get("Times"))
            values = fields.get("KeyValues", fields.get("Values"))
            if times and values:
                yield times["Value"], values["Value"]
        for child in value.values():
            yield from channels(child)
    elif isinstance(value, list):
        for child in value:
            yield from channels(child)


class CloudTrimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (DLL.exists() and USMAP.exists() and DONOR.exists()):
            raise unittest.SkipTest("Build ffr-dt and extract Cloud's 440111 sequence first")
        cls.temp = tempfile.TemporaryDirectory(prefix="cloud-trim-", dir=ROOT / "build")
        cls.work = Path(cls.temp.name).resolve()
        assert cls.work.is_relative_to((ROOT / "build").resolve())
        cls.addClassCleanup(cls.temp.cleanup)
        cls.assets = cls.work / "assets"
        shutil.copytree(DONOR, cls.assets)
        cls.files = sorted(cls.assets.rglob("*.uasset"))
        cls.before = {p.relative_to(cls.assets): cls.dump(p) for p in cls.files}
        recipe = generator.apply_cinematic({}, 440110)
        ops = []
        for cut in recipe["trim"]:
            for path in cls.files:
                ops.append({"asset": path.relative_to(cls.assets).with_suffix("").as_posix(),
                            "after": round(cut["after"] * 30) * 800,
                            "delta": round(cut["delta"] * 30) * 800, "cut": True})
        cls.patch(cls.assets, ops)
        cls.after = {p.relative_to(cls.assets): cls.dump(p) for p in cls.files}

    @classmethod
    def run_dt(cls, *args):
        result = subprocess.run(["dotnet", str(DLL), *map(str, args), "--usmap", str(USMAP)],
                                capture_output=True, text=True, encoding="utf-8")
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result.stdout

    @classmethod
    def dump(cls, path):
        target = cls.work / "dump.json"
        output = cls.run_dt("tojson", path, target)
        if "roundtrip=True" not in output:
            raise AssertionError(output)
        return json.loads(target.read_text(encoding="utf-8"))

    @classmethod
    def patch(cls, assets, frames):
        path = cls.work / "patch.json"
        path.write_text(json.dumps({"legacyRoot": str(assets), "outRoot": str(assets), "frames": frames}), encoding="utf-8")
        cls.run_dt("patch", path)

    def test_movie_and_sound_ranges_stay_valid(self):
        for path, asset in self.after.items():
            for export in asset["Exports"]:
                value = section_range(export)
                if not value:
                    continue
                lo, hi = value["LowerBound"], value["UpperBound"]
                if "Open" not in (lo["Type"], hi["Type"]):
                    self.assertLess(number(lo["Value"]), number(hi["Value"]), (path, export["ObjectName"]))
        master = self.after[Path("SEQ_Battle_440111_Master.uasset")]
        movie = next(e for e in master["Exports"] if e["ObjectName"] == "MovieSceneManaSection_1")
        value = section_range(movie)
        self.assertEqual(number(value["LowerBound"]["Value"]), 36000)
        self.assertEqual(number(value["UpperBound"]["Value"]), 43200)

    def test_events_keep_their_values_and_order(self):
        removed = 0
        for path, before in self.before.items():
            old = list(channels(before))
            new = list(channels(self.after[path]))
            self.assertEqual(len(old), len(new))
            for (old_times, old_values), (times, values) in zip(old, new):
                expected = []
                for time, value in zip(map(number, old_times), old_values):
                    # Delete the idle tail, then the movie, retaining both splice boundaries.
                    if 472800 <= time < 566400 or 36000 <= time < 356000:
                        removed += 1
                        continue
                    if time >= 566400:
                        time -= 93600
                    if time >= 356000:
                        time -= 320000
                    expected.append((time, value["Value"]))
                actual = list(zip(map(number, times), (v["Value"] for v in values)))
                self.assertEqual(actual, expected, path)
                self.assertEqual([v["Value"] for v in values[len(times):]], [v["Value"] for v in old_values[len(old_times):]], path)
                self.assertEqual(list(map(number, times)), sorted(map(number, times)), path)
        self.assertGreater(removed, 0)

    def test_fully_cut_sound_sections_are_detached(self):
        detached = 0
        for path, before in self.before.items():
            after = self.after[path]
            for index, export in enumerate(before["Exports"]):
                for field in export.get("Data", []):
                    if not isinstance(field, dict) or field.get("Name") != "AtomSections":
                        continue
                    kept = {v["Value"] for v in prop(after["Exports"][index], "AtomSections")["Value"]}
                    for ref in field["Value"]:
                        bounds = section_range(before["Exports"][ref["Value"] - 1])
                        if bounds and bounds["LowerBound"]["Type"] != "Open" and bounds["UpperBound"]["Type"] != "Open":
                            lo, hi = number(bounds["LowerBound"]["Value"]), number(bounds["UpperBound"]["Value"])
                            if 36000 <= lo <= hi < 356000:
                                self.assertNotIn(ref["Value"], kept)
                                detached += 1
        self.assertGreater(detached, 0)

    def test_positive_stretch_keeps_all_events(self):
        assets = self.work / "stretch"
        shutil.copytree(DONOR, assets)
        path = Path("Track/SEQ_Battle_440111_Cut_000.uasset")
        self.patch(assets, [{"asset": path.with_suffix("").as_posix(), "after": 356001, "delta": 24000}])
        stretched = self.dump(assets / path)
        for (old_times, old_values), (times, values) in zip(channels(self.before[path]), channels(stretched)):
            self.assertEqual(values, old_values)
            self.assertEqual(list(map(number, times)), [t + 24000 if t >= 356001 else t for t in map(number, old_times)])

    def test_movie_mute_still_applies_after_cut(self):
        assets = self.work / "muted"
        assets.mkdir()
        name = "SEQ_Battle_440111_Master"
        for extension in (".uasset", ".uexp"):
            shutil.copy2(self.assets / (name + extension), assets)
        patch = self.work / "mute.json"
        with mock_patch.object(generator, "seq_dumps", return_value=(self.before[Path(name + ".uasset")], None)):
            movie_ops = generator.movie_ops(str(DONOR / (name + ".uasset")))
        patch.write_text(json.dumps({"legacyRoot": str(assets), "outRoot": str(assets), "objects": [
            {"asset": name, "export": export, "set": fields}
            for export, fields in movie_ops
        ]}), encoding="utf-8")
        self.run_dt("patch", patch)
        muted = self.dump(assets / (name + ".uasset"))
        movie = next(e for e in muted["Exports"] if e["ObjectName"] == "MovieSceneManaSection_1")
        self.assertEqual(prop(movie, "ManaSource")["Value"], 0)
        spawn = next(e for e in muted["Exports"] if e["ObjectName"] == "MovieSceneSpawnSection_0")
        curve = {p["Name"]: p["Value"] for p in prop(spawn, "BoolCurve")["Value"]}
        self.assertTrue(curve["Values"])
        self.assertTrue(all(v["Value"] is False for v in curve["Values"]))
        self.assertEqual(list(map(number, curve["Times"])), sorted(map(number, curve["Times"])))


if __name__ == "__main__":
    unittest.main()
