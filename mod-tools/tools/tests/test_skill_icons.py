"""Source defaults, explicit edits, lookup registration and portable previews."""
from collections import defaultdict
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/devui')]
import skill_icons
import vision_icons


class SkillIconTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.icons = Path(self.tmp.name)
        Image.new('RGBA', (112,112), (12,34,56,200)).save(self.icons/'ability_77.png')
        Image.new('RGBA', (112,112), (56,34,12,200)).save(self.icons/'global_ability_10086.png')
        (self.icons/'aliases.json').write_text(json.dumps({'700000077':'ability_77.png'}))
        p = patch.object(skill_icons, 'ICONS', self.icons); p.start(); self.addCleanup(p.stop)

    def test_source_ids_resolve_and_path_traversal_is_rejected(self):
        self.assertEqual(skill_icons.path('700000077'),self.icons/'ability_77.png')
        for name in ('../ability_77.png', '/ability_77.png', 'bad.png', r'..\ability_77.png'):
            self.assertIsNone(skill_icons.path(name))
        self.assertEqual(len(skill_icons.catalog()),2)

    def test_original_icon_default_and_explicit_overrides(self):
        r={'ffbe':{'icon':'700000077'},'set':{'SkillIcon.TagName':'UI.Skill.Action.Icon.Fire'}}
        self.assertEqual(skill_icons.recipe_tag(r),skill_icons.tag('ability_77.png'))
        self.assertEqual(skill_icons.recipe_tag(r,{'icon':'UI.Skill.Action.Icon.Ice'}),'UI.Skill.Action.Icon.Ice')
        self.assertEqual(skill_icons.recipe_tag({**r,'iconChoice':''}),skill_icons.tag('ability_77.png'))
        with self.assertRaisesRegex(ValueError,'Missing FFBE'):
            skill_icons.recipe_tag({'ffbe':{'icon':'ability_999.png'}})

    def test_every_recipe_kind_shares_registered_textures(self):
        recipe={'ffbe':{'icon':'ability_77.png'}}
        u={'id':13500,'skills':{'1':deepcopy(recipe)},'convertedPassives':{'2':deepcopy(recipe)},
           'lb_custom':{'ffbe':{'icon':'global_ability_10086.png'}}}
        registry=vision_icons.registry_patch([u],{'Native':{'Tag':'DM.List.Main'}})
        tables=defaultdict(lambda:{'add':[]})
        names=skill_icons.prepare([u], lambda t:tables[t], lambda *args:('Fire',{}),registry)
        self.assertEqual(names,['ability_77.png','global_ability_10086.png'])
        self.assertEqual(len(registry['add']),3)
        for rel in skill_icons.TABLES:
            self.assertEqual(len(tables[rel]['add']),2)
            self.assertTrue(all(r['set']['Brush.bIsDynamicallyLoaded'] for r in tables[rel]['add']))
        self.assertEqual(u['skills']['1']['set']['SkillIcon.TagName'],u['convertedPassives']['2']['set']['SkillIcon.TagName'])

    def test_bgra_payload_preserves_transparency_and_dimensions(self):
        calls=[]
        skill_icons.build(['ability_77.png'], self.icons,self.icons/'out',self.icons/'work',['ffr-dt'],'map',calls.append)
        payload=(self.icons/'work/skill-icons/ability_77.bgra').read_bytes()
        self.assertEqual(len(payload),64*64*4)
        self.assertEqual(payload[3],200)
        self.assertLess(payload[2],payload[0])
        self.assertIn('/Game/UI/Textures/Icon/FFBE/FFBE_ability_77',calls[0])

    def test_both_preview_routes_serve_the_actual_source_bytes(self):
        import server
        from fastapi.testclient import TestClient
        client=TestClient(server.app)
        for url in ['/api/ffr/icon/ffbe_ability_77.png','/api/ffbe/abilityicon/700000077']:
            response=client.get(url)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.content,(self.icons/'ability_77.png').read_bytes())


if __name__ == '__main__': unittest.main()
