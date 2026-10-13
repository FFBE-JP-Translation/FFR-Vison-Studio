"""Focused coverage for the generated FFBE Limit Burst name lookup."""
import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
sys.path.insert(0, str(ROOT / "tools/devui"))
import lb_names  # noqa: E402


class LimitBurstNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lb_names.translations.cache_clear()
        cls.data = lb_names.translations()

    def test_every_generated_id_name_pair_resolves(self):
        for lb_id, names in self.data["byId"].items():
            for jp, english in names.items():
                self.assertEqual(english, lb_names.english_name(lb_id, jp), (lb_id, jp))

    def test_every_tracked_editorial_name_resolves_to_english(self):
        editorial = {}
        for path in sorted((ROOT / "docs/translations").glob("lb_names_batch*.json")):
            editorial.update({jp: english for jp, english in json.loads(path.read_text(encoding="utf-8")).items()
                              if not jp.startswith("_")})
        self.assertEqual(371, len(editorial))
        for jp, english in editorial.items():
            self.assertFalse(JP_RE.search(english), jp)
            self.assertEqual(english, lb_names.english_name(name=jp), jp)

    def test_mismatched_selected_name_does_not_use_id_default(self):
        lb_id, names = next((lb_id, names) for lb_id, names in self.data["byId"].items() if names)
        default = next(iter(names.values()))
        self.assertIsNone(lb_names.english_name(lb_id, "__different_lb_name__"))
        self.assertNotEqual(default, lb_names.english_name(lb_id, "__different_lb_name__"))


if __name__ == "__main__":
    unittest.main()
