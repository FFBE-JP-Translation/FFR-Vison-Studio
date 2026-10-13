"""Catalog consumers must not export or certify incomplete or stale mechanics."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
from ability_converter import Converter, SourceRecord
from ability_converter.availability import write_plans
from ability_converter.catalog import SourceCatalog
from ability_converter.cli import build, build_catalog, dump, export
from ability_converter.native import NativeCatalog
from ability_converter.runs import implementation_hashes, require_current_run
from ability_converter.sources import ARTIFACTS, read
from ability_converter.verify import verify


class CatalogConsumption(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name)
        self.args = SimpleNamespace(out=self.out, artifacts=ARTIFACTS, output=None, id=None,
            datamine=None, client=None, archive=None, sources="gl", max_level=False, limit=None, strict=False)
        self.compiler = Converter()
        self.build()
        self.report = read(self.out/"report.json")
        self.run = read(self.out/"run.json")
        self.args.id = "TEST/ability/1"

    def build(self):
        with SourceCatalog(self.out/"source-index.sqlite") as catalog:
            for sid, extra in (("1", []), ("2", [[0,3,1014,[2,2,1,1,1,0]]])):
                catalog.add(SourceRecord("TEST","ability",sid,{"name":"Catalog fixture", "mp_cost":10,
                    "effects_raw":[*extra,[1,1,1,[0,0,0,0,0,0,500,0]]],
                    "attack_frames":[[12]],"attack_damage":[[100]]}))
            catalog.finish()
            with redirect_stdout(io.StringIO()):
                return build_catalog(self.args, catalog)

    def rejected_consumers(self, message):
        for name, consume in (("export",lambda:export(self.args)),
                              ("verify",lambda:verify(Converter(self.args.artifacts),self.out)),
                              ("availability",lambda:write_plans(self.args))):
            with self.subTest(consumer=name), self.assertRaisesRegex(ValueError,message):
                consume()
        self.assertFalse((self.out/"selected-ability.json").exists())
        self.assertFalse((self.out/"verification").exists())
        self.assertFalse((self.out/"availability-plans.jsonl").exists())

    def test_completed_current_catalog_exports_stable_native_ids(self):
        self.assertEqual(require_current_run(self.out,self.compiler)["records"],2)
        before = (self.out/"ids.json").read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(export(self.args),0)
        exported = read(self.out/"selected-ability.json")
        self.assertEqual(exported["source"]["key"],self.args.id)
        converted = json.loads((self.out/"converted.jsonl").read_text(encoding="utf-8").splitlines()[0])
        skill_table = next(t for t in exported["tables"] if t["asset"].endswith("Skill/DT_SkillData"))
        self.assertEqual(skill_table["add"][0]["set"]["ID"],converted["destinationId"])
        self.assertEqual((self.out/"ids.json").read_bytes(),before)

    def test_incompatible_ledger_is_rejected_before_reindex_or_output_changes(self):
        ledger = read(self.out/'ids.json')
        ledger['skills']['TEST/ability/1'] = 10000000
        dump(self.out/'ids.json', ledger)
        paths = ['source-index.sqlite', 'ids.json', 'run.json', 'report.json', 'converted.jsonl']
        before = {name:(self.out/name).read_bytes() for name in paths}
        with self.assertRaisesRegex(ValueError, 'native range'):
            build(self.args)
        self.assertEqual(before, {name:(self.out/name).read_bytes() for name in paths})

    def test_partial_old_schema_and_mismatched_markers_cannot_be_certified(self):
        for overrides, message in (({"status":"running"},"not completed"),
                                   ({"schemaVersion":"older"},"schema"),
                                   ({"records":3},"completion marker"),
                                   ({"records":True},"completion marker")):
            with self.subTest(overrides=overrides):
                dump(self.out/"run.json",{**self.run,**overrides})
                self.rejected_consumers(message)
        dump(self.out/"run.json",self.run)
        dump(self.out/"report.json",{**self.report,"schemaVersion":"older"})
        self.rejected_consumers("schema")

    def test_changed_added_missing_or_unfingerprinted_code_is_rejected(self):
        variants = [None, {**self.report["implementation"],"compiler.py":"old"},
                    {**self.report["implementation"],"removed_module.py":"old"},
                    {k:v for k,v in self.report["implementation"].items() if k != "compiler.py"}]
        for fingerprints in variants:
            with self.subTest(fingerprints=fingerprints is None):
                dump(self.out/"report.json",{**self.report,"implementation":fingerprints})
                self.rejected_consumers("implementation")

    def test_changed_generated_artifact_is_rejected_before_any_output(self):
        directory = self.out/"changed-artifacts"
        directory.mkdir()
        for name in ("ffr-effects.json","ffbe-effects.json","proposed-map.json","proposed-policies.json"):
            shutil.copyfile(ARTIFACTS/name,directory/name)
        path = directory/"proposed-policies.json"
        path.write_bytes(path.read_bytes()+b"\n")
        self.args.artifacts = directory
        self.rejected_consumers("conversion inputs changed.*proposed-policies")

    def test_each_native_reference_and_an_already_loaded_catalog_are_checked(self):
        directory = self.out/"native-rows"
        for name,path in self.compiler.native.reference_paths.items():
            destination = directory/name
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,destination)
        for name in self.compiler.native.reference_paths:
            with self.subTest(table=name):
                path = directory/name
                original = path.read_bytes()
                loaded = Converter(native=NativeCatalog(rows=directory))
                path.write_bytes(original+b"\n")
                with self.assertRaisesRegex(ValueError,"loaded conversion inputs changed"):
                    require_current_run(self.out,loaded)
                changed = Converter(native=NativeCatalog(rows=directory))
                with self.assertRaisesRegex(ValueError,"conversion inputs changed"):
                    verify(changed,self.out)
                path.write_bytes(original)
        self.assertFalse((self.out/"verification").exists())

    def test_code_change_during_build_leaves_the_run_incomplete(self):
        self.args.id = None
        current = implementation_hashes()
        with patch("ability_converter.cli.implementation_hashes",side_effect=[current,{**current,"compiler.py":"changed"}]):
            with self.assertRaisesRegex(ValueError,"implementation changed"):
                self.build()
        self.assertEqual(read(self.out/"run.json")["status"],"running")
        self.rejected_consumers("not completed")


if __name__ == "__main__":
    unittest.main()
