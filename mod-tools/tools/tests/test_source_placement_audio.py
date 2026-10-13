"""Missing visual adapters must not erase retained source sound events."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from ffbe_effects import prepare_vision as prepare


class SourcePlacementAudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / 'data/ffbe/native_kits/340000107.json'
        if not path.is_file():
            raise unittest.SkipTest('Local Sora source snapshots required')
        cls.kit = json.loads(path.read_text(encoding='utf-8'))

    def test_all_five_sunray_variants_preserve_projectile_hit_sounds(self):
        for ident in range(237607, 237612):
            with self.subTest(ability=ident):
                snapshot = self.kit['profiles'][f'GL_2024/ability/{ident}']['snapshot']
                data = prepare.timeline(snapshot, include_screen=True)
                self.assertEqual([68, 74, 80, 86, 92, 98, 104, 110],
                                 [s['frame'] for s in data['sounds'] if s['cueId'] == 100])
                # Recovery of its sound cues does not imply projectile art
                # already has a working native placement adapter.
                self.assertFalse(data['visualCoverage']['complete'])
                self.assertTrue(any(o.get('groupId') == '20100030'
                                    for o in data['visualCoverage']['omitted']))
                self.assertFalse(any(s['groupId'] == '20100030' for s in data['spawns']))
                audit = next(g for g in data['sourcePlacement']['groups'] if g['groupId'] == '20100030')
                self.assertTrue(audit['skill']['supported'])
                self.assertEqual(audit['skill']['travelFrames'], 7)
                self.assertEqual(audit['skill']['startRect']['owner'], 'caster')
                self.assertEqual(audit['skill']['destinationRect']['owner'], 'target')
                self.assertEqual(len(audit['effects']), 8)
                self.assertTrue(all(e['supported'] for e in audit['effects']))
                self.assertTrue(all(e['axes']['x']['alignment'] == 'center' for e in audit['effects']))
                self.assertIs(data['sourcePlacement']['applied'], False)

    def test_omitted_mechanical_component_does_not_gain_its_sounds(self):
        snapshot = self.kit['profiles']['GL_2024/ability/237607']['snapshot']
        original = prepare.catalog.skill_effects

        def with_discarded_component(kind, ident):
            result = deepcopy(original(kind, ident))
            if str(ident) == '237607':
                for group in result['groups']:
                    if group['groupId'] == '20100030':
                        group['component'] = 999
            return result

        with patch.object(prepare.catalog, 'skill_effects', side_effect=with_discarded_component):
            data = prepare.timeline(snapshot, include_screen=True)
        self.assertFalse(any(s['cueId'] == 100 for s in data['sounds']))
        self.assertTrue(any('component 999: omitted mechanics' in s for s in data['issues']))


if __name__ == '__main__':
    unittest.main()
