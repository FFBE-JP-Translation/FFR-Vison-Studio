"""The audit must keep failures visible without claiming gameplay coverage."""
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import audit_resonances as audit
from PIL import Image


def source():
    return {"lbId": "10", "name": "Example", "moveType": 1, "elements": [], "damageComponent": 0,
            "hitFrames": [30], "hitPercents": [100], "components": [
                {"index": 0, "type": 1, "target": 1, "range": 1, "params": [], "multiplier": 3}],
            "movement": {"ffrTargetOffset": [0, 40, 0]}, "warnings": []}


CASE = {"caseId": "123:123:GL:10", "unitId": "123", "name": "Example", "roles": ["Attacker"],
        "formId": "123", "region": "GL", "lbId": "10", "studioRegion": True, "defaultLb": True}
CLOUD = {**dict.fromkeys(("skillAttrType", "skillEffectType", "parameterType", "parameterVariationType"), "fixture"),
         "accuracy": 500, "criticalHitRate": 25, "Cost": 0, "breakDamageValue": 0, "effectBundleList": [], "magnification": 36}


class AuditTests(unittest.TestCase):
    def run_case(self, data, *, author_error=None, audio_warnings=None):
        sources = Mock(raw=Mock(return_value={"diagnostic": "raw data"}))
        motion = Mock(check=Mock(return_value={"seconds": 1, "warnings": []}))
        audio = Mock(check=Mock(return_value={"events": [], "warnings": audio_warnings or []}))
        with patch.object(audit.ffbe_lb, "resolve", side_effect=data if isinstance(data, Exception) else None,
                          return_value=data), patch.object(audit.ffbe_resonance, "author", side_effect=author_error, return_value=[{}]):
            return audit.audit_case(CASE, sources, motion, audio, {}, CLOUD)

    def test_pass_is_preflight_and_side_effects_remain_visible(self):
        data = source()
        data["components"].append({"index": 1, "type": 33, "target": 1, "range": 2, "params": []})
        result = self.run_case(data)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checks"]["authoring"], "PASS")
        self.assertEqual(result["gameplay"], "NOT_RUN")
        self.assertEqual(result["cookedPackage"], "NOT_RUN")
        self.assertIn("mechanics.side_effects_not_imported", [r["code"] for r in result["warnings"]])

    def test_support_lb_records_reason_and_still_checks_motion_and_audio(self):
        data = source(); data.pop("damageComponent"); data.pop("hitFrames")
        data["components"] = [{"index": 0, "type": 3, "target": 2, "range": 2, "params": []}]
        result = self.run_case(data)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failures"][0]["code"], "support.unsupported_component")
        self.assertEqual(result["checks"]["motion"], "PASS")
        self.assertEqual(result["checks"]["audio"], "PASS")
        self.assertEqual(result["checks"]["authoring"], "BLOCKED")

    def test_one_bad_source_does_not_stop_the_next_case(self):
        bad = self.run_case(ValueError("Malformed first variant"))
        good = self.run_case(source())
        self.assertEqual((bad["status"], good["status"]), ("FAIL", "PASS"))
        self.assertIn("Malformed first variant", bad["exceptions"]["source"])
        self.assertEqual(bad["rawLb"], {"diagnostic": "raw data"})

    def test_authoring_failure_is_not_a_pass(self):
        result = self.run_case(source(), author_error=ValueError("No event functions remain"))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failures"][0]["code"], "authoring.exception")

    def test_unexpected_diagnostic_failure_does_not_stop_the_next_case(self):
        with patch.object(audit, "raw_types", side_effect=ValueError("Bad raw level")):
            bad = self.run_case(ValueError("Bad source"))
        good = self.run_case(source())
        self.assertEqual((bad["status"], good["status"]), ("FAIL", "PASS"))
        self.assertEqual(bad["failures"][0]["code"], "audit.exception")
        self.assertIn("Bad raw level", bad["exceptions"]["audit"])

    def test_raw_effects_classify_parser_failures_without_calling_them_support(self):
        self.assertEqual(audit.family(audit.raw_types({"effect_type": "1@33@3"})), "single_damage")
        raw = {"levels": {"1": {"effects_raw": [[2, 1, 15, []], [2, 1, 1, []]]}}}
        self.assertEqual(audit.family(audit.raw_types(raw)), "multiple_damage")
        self.assertEqual(audit.family([3, 111]), "support_or_other")

    def test_omitted_audio_is_partial_without_hiding_the_warning(self):
        result = self.run_case(source(), audio_warnings=[audit.issue("audio.omitted_cues", "88")])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["checks"]["audio"], "PARTIAL")
        self.assertEqual(result["warnings"][0]["message"], "88")

    def test_enumerates_all_variants_and_regions_before_resolving(self):
        sources = Mock(available=Mock(return_value=True), primary_region=Mock(return_value="GL"))
        sources.variants.side_effect = lambda form, region: ["bad", "good"] if region == "GL" else ["jp"]
        units = [{"id": "123", "name": "Agnès", "forms": ["123", "124"], "source": "GL"}]
        cases = list(audit.cases(units, sources, query="agnes"))
        self.assertEqual(len(cases), 6)
        self.assertEqual(len({c["caseId"] for c in cases}), 6)
        self.assertEqual(sum(c["studioRegion"] for c in cases), 4)
        self.assertEqual(len(list(audit.cases(units, sources, "studio", "124"))), 2)

    def test_variants_follow_gl_precedence_and_jp_fallback(self):
        sources = audit.Sources.__new__(audit.Sources)
        sources.master_units = {"123": {"lb_id": "30,31"}}
        sources.regional = {"GL": ({"123": {"limitburst_id": [10, 11]}}, {}, None), "JP": ({}, {}, None)}
        self.assertEqual(sources.variants("123", "GL"), ["10", "11"])
        self.assertEqual(sources.variants("123", "JP"), ["30", "31"])
        sources.regional["GL"][0].clear()
        self.assertEqual(sources.variants("123", "GL"), ["30", "31"])

    def test_primary_region_uses_studio_membership_instead_of_merged_display_flag(self):
        sources = audit.Sources.__new__(audit.Sources)
        sources.unit_regions = {"123": "JP"}
        self.assertEqual(sources.primary_region({"id": "123", "source": "GL"}), "JP")
        self.assertEqual(sources.primary_region({"id": "456", "source": "GLW"}), "GL")

    def test_shared_long_sequence_is_classified_by_its_actual_hit_count(self):
        data = source(); data.pop("hitFrames"); data.pop("damageComponent")
        data["components"].insert(0, {"index": 0, "type": 3, "target": 2, "range": 2})
        data["components"][1]["index"] = 1
        data["rawAttackFrames"] = "-".join(f"{i}:2" for i in range(50))
        result = self.run_case(data)
        self.assertEqual(result["failures"][0]["code"], "mechanics.over_30_hits")

    def test_reports_mixed_units_and_comparison_without_counting_untested_cases_as_fixed(self):
        good = self.run_case(source())
        bad = self.run_case(ValueError("broken")); bad["caseId"] = "123:124:GL:11"; bad["formId"] = "124"
        previous = [deepcopy(good), deepcopy(bad), {**deepcopy(bad), "caseId": "not-retested"}]
        previous[0]["status"] = "FAIL"
        with tempfile.TemporaryDirectory(prefix="audit-test-", dir=ROOT / "build") as work:
            self.assertTrue(Path(work).resolve().is_relative_to((ROOT / "build").resolve()))
            summary = audit.write_reports(work, [good, bad], {"schema": 1}, previous)
            self.assertEqual(summary["units"], {"MIXED": 1})
            self.assertEqual(summary["comparison"]["fixed"], [good["caseId"]])
            self.assertEqual(summary["comparison"]["notRetested"], ["not-retested"])
            with Path(work, "failures.csv").open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(len(rows), 1)
            self.assertIn("broken", rows[0]["failures"])
            self.assertTrue(json.loads(Path(work, "summary.json").read_text())["complete"])


class MotionTests(unittest.TestCase):
    def inspect(self, frame):
        with tempfile.TemporaryDirectory(prefix="audit-motion-", dir=ROOT / "build") as work:
            self.assertTrue(Path(work).resolve().is_relative_to((ROOT / "build").resolve()))
            output = Path(work)
            png = io.BytesIO(); Image.new("RGBA", (2, 2), "white").save(png, format="PNG")
            with zipfile.ZipFile(output / "123.zip", "w") as archive:
                archive.writestr("unit_anime_123.png", png.getvalue())
                archive.writestr("unit_cgg_123.csv", "0,1,0,0,0,0,100,0,0,0,2,2,0\n")
                archive.writestr("unit_limit_atk_cgs_123.csv", f"{frame},0,0,60\n")
            return audit.MotionFiles(output, output).check("123")

    def test_underscore_alias_uses_converter_timing(self):
        self.assertEqual(self.inspect(0)["seconds"], 1)

    def test_invalid_lb_frame_is_a_failure(self):
        with self.assertRaisesRegex(ValueError, "missing composition frame"):
            self.inspect(5)


if __name__ == "__main__":
    unittest.main()
