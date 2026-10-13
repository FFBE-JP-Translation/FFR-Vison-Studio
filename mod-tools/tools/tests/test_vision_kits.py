"""Reviewed Studio imports keep all forms and survive save/build/loadout edits."""
from copy import deepcopy
from collections import defaultdict
import json
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'tools/devui')]
from ability_converter import commands, reviewed
from ability_converter.sources import SourceRecord
import reviewed_kits
import vision_import


def fixture(form='340000107'):
    return {'id': 13500, 'key': 'reviewed-test', 'jp': 'Fixture', 'command': {'id': 320},
        'ffbe': {'id': form, 'source': 'GL'}, 'skills': {}, 'awakening': [[], [], [], []], 'synchro': []}


class VisionKitTests(unittest.TestCase):
    def test_missing_optional_motion_uses_the_same_idle_as_sprite_builder(self):
        import make_vision_mod
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'unit_idle_cgs_1.csv').write_text('0,0,0,12\n0,0,0,18\n')
            u = {'ffbe': {'id': '1', 'dir': directory}}
            self.assertEqual(make_vision_mod.command_motion_seconds(u,'magic_attack'),.5)
            self.assertEqual(make_vision_mod.lb_motion_seconds(u),.5)

    def test_shift_uses_its_own_membership_and_full_library(self):
        base, shift = reviewed_kits.kit('340000107'), reviewed_kits.kit('340000117')
        self.assertNotEqual(base['owner'], shift['owner'])
        self.assertNotEqual({e['sourceKey'] for e in base['entries']}, {e['sourceKey'] for e in shift['entries']})
        u = fixture(); vision_import.hydrate(u)
        self.assertEqual([e['sourceKey'] for e in u['ffbeLibrary']],
                         [e['sourceKey'] for e in base['entries'] if e.get('disabledBy') != 'multicast'])
        self.assertFalse(u['skills'])
        self.assertEqual(u['awakening'], [[], [], [], []])
        self.assertGreater(len(u['ffbeLibrary']), len(u['skills']))
        saved = deepcopy(u); vision_import.hydrate(u); self.assertEqual(u, saved)

    def test_loadout_swap_preserves_full_kit_and_native_size(self):
        u = fixture(); vision_import.import_native(u, 'abilities')
        old = next(iter(u['skills']))
        ability = next(e for e in u['ffbeLibrary'] if e['status'] == 'ready' and e['kind'] in ('ABILITY','MAGIC') and not vision_import.imported(u,e['sourceKey']))
        original_library = deepcopy(u['ffbeLibrary'])
        vision_import.equip(u, ability['sourceKey'], old)
        self.assertEqual(u['ffbeLibrary'], original_library)
        self.assertTrue(vision_import.imported(u, ability['sourceKey']))
        self.assertLessEqual(len(u['skills']), 10)
        self.assertTrue(all(len(t) <= 8 for t in u['awakening']))
        group, sid = vision_import.imported(u, ability['sourceKey'])
        vision_import.remove(u, group, sid)
        self.assertEqual(u['ffbeLibrary'], original_library)

    def test_existing_authored_skill_is_preserved(self):
        u=fixture(); original={'en':'Authored move','from':445020,'set':{'magnification':99}}
        u['skills']['485000']=deepcopy(original);u['awakening'][0].append(['ActiveSkill',485000])
        vision_import.hydrate(u)
        self.assertEqual(u['skills']['485000'],original)
        self.assertIn(['ActiveSkill',485000],u['awakening'][0])

    def test_reviewed_resource_passive_materializes_once_at_start(self):
        for code in (32,33):
            r=SourceRecord('TEST','passive','1',{'effects_raw':[[0,3,code,[500 if code==33 else 10]]],'name':'Recovery'})
            p=commands.profile(r,reviewed=True)
            self.assertTrue(p['supported'],p['issues'])
            tables=defaultdict(lambda:{'add':[],'set':[]})
            commands.materialize_passive(p,51000,'fixture',lambda t:tables[t],lambda *args:('fixture',{}),'Recovery')
            row=tables['Skill/DT_PassiveSkillData']['add'][0]['set']
            self.assertEqual(row['effectBundleList'][0]['passiveSkillAddTiming'],'BeginBattle')
            effects=tables['Skill/DT_SkillEffectData']['add']
            self.assertTrue(effects)
            self.assertTrue(all(e['set']['applyTiming']=='AddEffect' for e in effects))

    def test_api_returns_an_editable_draft_and_rejects_foreign_ability(self):
        from fastapi.testclient import TestClient
        import server
        client=TestClient(server.app);u=fixture()
        with patch.object(server,'save_spec') as save:
            r=client.post('/api/ffbe/kit/import',json={'unit':u})
            self.assertEqual(r.status_code,200,r.text);draft=r.json()
            self.assertTrue(draft['ffbeLibrary']);self.assertFalse(u['skills'])
            r=client.post('/api/ffbe/kit/loadout',json={'unit':draft,'sourceKey':'UNKNOWN/ability/1'})
            self.assertEqual(r.status_code,422)
            save.assert_not_called()


if __name__ == '__main__': unittest.main()
