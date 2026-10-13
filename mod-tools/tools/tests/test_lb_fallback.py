"""Unsupported LB mechanics remain explicit while imported visions can build."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffbe_lb as lb
import ffbe_resonance as resonance


class FallbackTests(unittest.TestCase):
    def test_unsupported_support_hits_elements_and_movement_get_neutral_fallback(self):
        samples = [
            {'components': [{'index': 0, 'type': 2, 'target': 2, 'range': 2}]},
            {'components': [{'index': 0, 'type': 1, 'target': 1, 'range': 2}],
             'damageComponent': 0, 'elements': ['Fire', 'Ice'], 'hitFrames': [30], 'hitPercents': [100]},
            {'components': [{'index': 0, 'type': 1, 'target': 1, 'range': 2}],
             'damageComponent': 0, 'moveType': 6, 'hitFrames': [30], 'hitPercents': [100]},
        ]
        for sample in samples:
            raw = {'lbId': 'example', 'moveType': 1, 'elements': [],
                   'sounds': [{'frame': 30, 'cueId': 1}], **sample}
            before = deepcopy(raw)
            with self.subTest(sample=sample), patch.object(lb, 'resolve', return_value=raw):
                self.assertFalse(lb.profile(raw)['supported'])
                source, result = lb.resolve_import({}, {})
                self.assertTrue(result['supported'])
                self.assertFalse(result['sourceSupported'])
                self.assertTrue(result['fallbackReasons'])
                self.assertEqual(result['mode'], 'fallback')
                self.assertEqual(result['fieldColor'], '#808080')
                expected_hits = len(raw.get('hitFrames', [])) or 10
                self.assertEqual((result['hits'], result['target'], result['elements']), (expected_hits, 'All enemies', []))
                self.assertEqual(result['totalPower'], lb.cloud_reference()['magnification'])
                self.assertAlmostEqual(sum(result['set']['hitDamageRatioList']), 1)
                self.assertFalse(result['set']['isHostilityRelationTargetingDisabled'])
                self.assertTrue(result['set']['isSameRelationTargetingDisabled'])
                self.assertFalse(result['set']['isReverseDamageToUndead'])
                self.assertEqual(result['set']['totalDamageDisplayRule'], 'Default')
                self.assertEqual(source['sounds'], raw['sounds'])
                self.assertEqual(source.get('hitFrames'), raw.get('hitFrames'))
                plan = resonance.schedule(5, expected_hits, 444010, source)
                types = [e['set']['EventType'] for e in plan['events']]
                self.assertEqual(types.count('OtherReaction'), expected_hits)
                self.assertEqual('UnitMoveToTarget' in types, raw['moveType'] == 1)
                self.assertEqual(types[-1], 'PostSetDefaultColorGrading')
                self.assertEqual(raw, before)

    def test_missing_or_invalid_source_is_reported_without_blocking_the_import(self):
        for mock in ({'return_value': None}, {'side_effect': ValueError('Invalid source hit weights')}):
            with patch.object(lb, 'resolve', **mock):
                source, result = lb.resolve_import({}, {})
                self.assertEqual(result['mode'], 'fallback')
                self.assertTrue(result['fallbackReasons'])
                self.assertEqual(source['moveType'], 0)

    def test_supported_mechanics_and_presentation_are_preserved(self):
        raw = {'lbId': 'working', 'moveType': 1, 'elements': ['Fire'],
               'components': [{'index': 0, 'type': 1, 'target': 1, 'range': 1}],
               'damageComponent': 0, 'hitFrames': [20, 40], 'hitPercents': [30, 70]}
        with patch.object(lb, 'resolve', return_value=raw):
            source, result = lb.resolve_import({}, {})
        self.assertIs(source, raw)
        self.assertTrue(result['sourceSupported'])
        self.assertEqual(result['set'], lb.profile(raw)['set'])
