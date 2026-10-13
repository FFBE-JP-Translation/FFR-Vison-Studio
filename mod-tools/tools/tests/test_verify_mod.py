"""Serialization differences and converted bindings must not hide real table changes."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_mod import equivalent, expected_general_change


class VerificationTests(unittest.TestCase):
    def test_signed_zero_matches_numeric_zero_inside_structs_and_arrays(self):
        self.assertTrue(equivalent({'color': {'X': '+0', 'Y': ['-0', 1]}},
                                   {'color': {'X': 0.0, 'Y': [0.0, 1.0]}}))
        self.assertTrue(equivalent(0, '+0'))

    def test_changes_missing_fields_and_nonzero_text_still_fail(self):
        for a, b in [(0, 0.000001), ('+0', 0.01), ('0', 0), ('+0', False),
                     ({'X': '+0'}, {}), ([0], [0, 0]), ({'name': 'one'}, {'name': 'two'})]:
            with self.subTest(a=a, b=b):
                self.assertFalse(equivalent(a, b))


class GeneralBindingVerificationTests(unittest.TestCase):
    def setUp(self):
        self.rel = 'Skill/Other/DT_SkillGeneralData'
        self.original = {'equipperActionVisionSkills': [414610],
                         'additionalCostData': [{'SkillId': 406110, 'Cost': 4}],
                         'costCheckData': [], 'unrelatedSetting': 7}
        self.settings = {'equipperActionVisionSkills': [414610, 485000],
                         'additionalCostData': [*self.original['additionalCostData'],
                                                {'SkillId': 485000, 'Cost': 2}]}
        self.built = {**deepcopy(self.original), **deepcopy(self.settings)}
        self.planned = {'tables': [{'asset': 'FFRS/Content/Datatable/' + self.rel,
                                  'set': [{'row': 'NewRow', 'set': self.settings}]}]}

    def accepted(self):
        return expected_general_change(self.rel, 'NewRow', self.original, self.built, self.planned)

    def test_planned_binding_and_cost_appends_pass(self):
        self.assertTrue(self.accepted())

    def test_missing_recipe_or_wrong_row_fails(self):
        self.assertFalse(expected_general_change(self.rel, 'NewRow', self.original, self.built, {}))
        self.assertFalse(expected_general_change(self.rel, 'OtherRow', self.original, self.built, self.planned))

    def test_unplanned_binding_fails(self):
        self.built['equipperActionVisionSkills'].append(485001)
        self.assertFalse(self.accepted())

    def test_native_entry_changes_fail_even_if_planned(self):
        for values in ([], [485000], [485000, 414610]):
            with self.subTest(values=values):
                self.settings['equipperActionVisionSkills'] = values
                self.built['equipperActionVisionSkills'] = values
                self.assertFalse(self.accepted())

    def test_unrelated_changes_fail_even_if_planned(self):
        self.built['unrelatedSetting'] = 8
        self.assertFalse(self.accepted())
        self.settings['unrelatedSetting'] = 8
        self.assertFalse(self.accepted())
