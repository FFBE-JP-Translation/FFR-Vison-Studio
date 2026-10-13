"""Native skill categories, persistent ledgers and private application IDs."""
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ability_converter.compiler import TableWriter
from ability_converter.effect_ids import OwnedEffectWriter, SKILL_START, SKILL_STOP
from ability_converter.skill_ids import vision_passive_base


def empty():
    return {'skills': {}, 'passives': {}, 'effects': {}}


class SkillIdTests(unittest.TestCase):
    def setUp(self):
        self.native = SimpleNamespace(skill_ids={100000, 100002}, passive_ids={1000, 1002}, effects={100000000})

    def test_native_rows_are_skipped_in_each_category(self):
        writer = TableWriter(self.native)
        for kind, expected in (('skills', [100001, 100003]), ('passives', [1001, 1003]),
                               ('effects', [100000001, 100000002])):
            self.assertEqual([writer.allocate(kind, str(i)) for i in range(2)], expected)

    def test_vision_passive_banks_cover_valid_native_slots_without_overlap(self):
        self.assertEqual((vision_passive_base(13100), vision_passive_base(13999)), (10000,99900))
        self.assertEqual(vision_passive_base(13501)-vision_passive_base(13500), 100)
        for value in (13099,14000,13500.0,True):
            with self.assertRaisesRegex(ValueError, 'vision ID'):
                vision_passive_base(value)

    def test_persisted_ids_survive_reordered_exports_and_fill_holes(self):
        ledger = empty()
        ledger['skills'] = {'last': 999999, 'first': 100001}
        writer = TableWriter(self.native, deepcopy(ledger))
        self.assertEqual(writer.allocate('skills', 'first'), 100001)
        self.assertEqual(writer.allocate('skills', 'last'), 999999)
        self.assertEqual(writer.allocate('skills', 'new'), 100003)
        replay = TableWriter(self.native, deepcopy(writer.ledger))
        self.assertEqual(replay.allocate('skills', 'new'), 100003)

    def test_wrong_categories_and_noninteger_ids_reject_without_remapping(self):
        for kind, values in (('skills', (99999, 1000000, 10000000, True, '100001', 100001.0)),
                             ('passives', (999, 100000, 20000000)),
                             ('effects', (0, -1, 2147483647))):
            for value in values:
                ledger = empty(); ledger[kind]['bad'] = value
                before = deepcopy(ledger)
                with self.subTest(kind=kind, value=value), self.assertRaisesRegex(ValueError, 'native range'):
                    TableWriter(self.native, ledger)
                self.assertEqual(ledger, before)

    def test_malformed_ledgers_are_rejected(self):
        for ledger in ({}, [], {**empty(), 'extra': {}}, {**empty(), 'skills': []},
                       {**empty(), 'skills': {'': 100001}}):
            with self.subTest(ledger=ledger), self.assertRaisesRegex(ValueError, 'ledger'):
                TableWriter(self.native, ledger)

    def test_duplicate_and_stock_collisions_are_rejected(self):
        for entries in ({'a': 100001, 'b': 100001}, {'a': 100000}):
            with self.assertRaisesRegex(ValueError, 'colliding'):
                TableWriter(self.native, {**empty(), 'skills': entries})

    def test_full_skill_bank_fails_without_entering_master_range(self):
        writer = TableWriter(self.native)
        writer.used['skills'].update(range(100000, 1000000))
        with self.assertRaisesRegex(ValueError, 'skills ID range exhausted'):
            writer.allocate('skills', 'overflow')
        self.assertNotIn('overflow', writer.ledger['skills'])

    def test_last_passive_slot_is_usable_but_no_active_id_can_follow(self):
        writer = TableWriter(self.native)
        writer.used['passives'].update(range(1000, 99999))
        self.assertEqual(writer.allocate('passives', 'last'), 99999)
        with self.assertRaisesRegex(ValueError, 'passives ID range exhausted'):
            writer.allocate('passives', 'overflow')

    def test_private_children_are_active_and_deterministic_across_owners(self):
        values = []
        for owner in (445010, 445010, 445020):
            writer = OwnedEffectWriter(self.native, {**empty(), 'skills': {'root': owner}}, owner, ())
            ids = [writer.allocate('skills', 'child/'+str(i)) for i in range(150)]
            self.assertTrue(all(SKILL_START <= value < SKILL_STOP for value in ids))
            self.assertEqual(len(set(ids)), 150)
            self.assertEqual(writer.allocate('skills', 'root'), owner)
            self.assertEqual(writer.allocate('skills', 'child/0'), ids[0])
            values.append(ids)
        self.assertEqual(values[0], values[1])
        self.assertNotEqual(values[0], values[2])

    def test_private_children_reject_other_package_rows_without_changing_ids(self):
        proposed = OwnedEffectWriter(self.native, empty(), 445010, ()).allocate('skills', 'child')
        writer = OwnedEffectWriter(self.native, empty(), 445010, (), [proposed, proposed+1])
        with self.assertRaisesRegex(ValueError, 'Duplicate converted application'):
            writer.allocate('skills', 'child')
        self.assertFalse(writer.ledger['skills'])


if __name__ == '__main__':
    unittest.main()
