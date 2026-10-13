"""Full inventory accounting and decision-file durability, isolated from user edits."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from tools.effect_review.serve import DIRECTORY, ReviewError, ReviewStore, validate_review


class EffectReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((DIRECTORY/'catalog.json').read_text(encoding='utf-8'))
        cls.defaults = json.loads((DIRECTORY/'mapping-defaults.json').read_text(encoding='utf-8'))

    def test_full_coverage_conservation(self):
        c = self.catalog['coverage']
        self.assertEqual(c['totalRecords'], 658544)
        self.assertEqual(sum(c['bySource'].values()), c['totalRecords'])
        self.assertEqual(sum(c['byKind'].values()), c['totalRecords'])
        self.assertEqual(sum(e['occurrences'] for e in self.catalog['effects']), c['components'])
        self.assertEqual(len(self.catalog['effects']), 346)
        self.assertEqual(len(self.catalog['ffr']), 194)
        self.assertFalse(c['sampled'])
        self.assertTrue(c['allLbLevels'])
        self.assertEqual(c['missingLeaderSkills'], [])
        self.assertEqual(sum('no parent master' in x['issue'] for x in c['anomalies']), 125)

    def test_user_rules_and_damage_song_correction(self):
        choices = self.defaults['decisions']
        self.assertEqual(choices['active:130']['targets'], ['policy:normal_cooldown'])
        self.assertEqual(choices['active:125']['targets'], ['preset:resonance_recovery'])
        self.assertEqual(choices['passive:33']['targets'], ['preset:resonance_recovery'])
        self.assertEqual(choices['active:30']['targets'], ['preset:mp_recovery'])
        self.assertNotEqual(choices['active:131']['targets'], ['preset:mp_recovery'])

    def test_round_trip_backup_and_stale_writer(self):
        with tempfile.TemporaryDirectory(prefix='ffr-effect-review-test-') as name:
            folder = Path(name)
            for file in ('catalog.json', 'mapping-defaults.json'):
                (folder/file).write_bytes((DIRECTORY/file).read_bytes())
            store = ReviewStore(folder)
            a, stale = store.current(), store.current()
            a['decisions']['active:1'] = {'targets': ['other'], 'notes': 'Keep <damage> & 日本語', 'reviewed': True}
            saved = store.save(a)
            self.assertEqual(saved['revision'], 1)
            self.assertEqual(store.current()['decisions']['active:1'], a['decisions']['active:1'])
            with self.assertRaisesRegex(ReviewError, 'conflict'):
                store.save(stale)
            saved['decisions']['active:1']['notes'] = 'Second edit'
            self.assertEqual(store.save(saved)['revision'], 2)
            backup = list((folder/'decision-backups').glob('*.json'))
            self.assertEqual(len(backup), 1)
            previous = json.loads(backup[0].read_text(encoding='utf-8'))
            self.assertEqual(previous['decisions']['active:1']['notes'], 'Keep <damage> & 日本語')

    def test_reject_wrong_snapshot_missing_effect_unknown_target(self):
        for field in ('snapshot', 'missing', 'target'):
            data = deepcopy(self.defaults)
            if field == 'snapshot': data['catalogId'] = 'wrong'
            if field == 'missing': del data['decisions']['active:1']
            if field == 'target': data['decisions']['active:1']['targets'] = ['ffr:Invented']
            with self.subTest(field=field), self.assertRaises(ReviewError):
                validate_review(data, self.catalog)

    def test_finish_requires_review_and_observed_other_notes(self):
        data = deepcopy(self.defaults)
        data['stage'] = 'ready'
        with self.assertRaisesRegex(ReviewError, 'all effects'):
            validate_review(data, self.catalog)
        for choice in data['decisions'].values(): choice['reviewed'] = True
        with self.assertRaisesRegex(ReviewError, 'needs notes'):
            validate_review(data, self.catalog)
        for choice in data['decisions'].values():
            if 'other' in choice['targets']: choice['notes'] = 'Keep unresolved for conversion report.'
        self.assertEqual(validate_review(data, self.catalog)['stage'], 'ready')

    def test_every_native_row_and_skill_is_accessible(self):
        guide = self.catalog['ffr']
        self.assertEqual(sum(len(t['effectRows']) for t in guide), 1006)
        self.assertEqual(sum(len(t['directSkillRows']) for t in guide), 1167)
        for entry in guide:
            self.assertTrue(entry['summary'])
            self.assertIn('ffr:'+entry['type'], {o['id'] for o in self.catalog['options']})


if __name__ == '__main__':
    unittest.main()
