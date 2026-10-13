"""Large rosters retain distinct, registered icons without changing native rows."""
from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import ffrenv
import make_vision_mod as generator
import vision_icons as icons
from verify_mod import equivalent


class CommandIconTests(unittest.TestCase):
    def test_large_roster_is_unique_and_independent_of_order(self):
        units = [{'id':13500+n} for n in range(64)]
        native = {'Native':{'Tag':'DM.List.Main', 'DevComment':''}}
        before = deepcopy(native)
        a = icons.registry_patch(units, native)
        b = icons.registry_patch(list(reversed(units)), native)
        self.assertEqual(len({v['set']['Tag'] for v in a['add']}), 64)
        self.assertEqual({v['row']:v['set'] for v in a['add']}, {v['row']:v['set'] for v in b['add']})
        self.assertEqual(a['set'], [])
        self.assertEqual(native, before)

    def test_duplicate_unit_id_is_reported_before_building(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate command icon'):
            icons.registry_patch([{'id':13500}, {'id':13500}], {'Native':{'Tag':'DM.List.Main'}})

    def test_both_icon_tables_receive_the_units_own_texture(self):
        tables = {}
        def tbl(rel): return tables.setdefault(rel, {'add':[], 'set':[]})
        for vid in (13500, 13516, 13563):
            icons.add_icon_rows({'id':vid}, tbl, lambda *args:('Cloud', {}))
        self.assertEqual(set(tables), set(icons.ICON_TABLES))
        for data in tables.values():
            self.assertEqual(data['set'], [])
            for row, vid in zip(data['add'], (13500, 13516, 13563)):
                self.assertEqual(row['set']['Tag.TagName'], icons.command_tag(vid))
                self.assertEqual(row['set']['Brush.ResourceObject'], f'/Game/UI/Textures/Icon/menu/ICON_Ability_summon{vid}')


class CookedCommandIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = ROOT/'extracted/legacy'; cls.usmap = ROOT/'extracted/Mappings.usmap'
        if not (cls.legacy/(icons.REGISTRY_ASSET+'.uasset')).is_file() or not cls.usmap.is_file():
            raise unittest.SkipTest('Prepare the native command-icon registry and mappings first')
        cls.temp = tempfile.TemporaryDirectory(prefix='command-icons-', dir=ROOT/'build')
        cls.work = Path(cls.temp.name).resolve()
        assert cls.work.is_relative_to((ROOT/'build').resolve())
        cls.addClassCleanup(cls.temp.cleanup)
        cls.assets = cls.work/'assets'
        native = cls.dump(cls.legacy/icons.REGISTRY_ASSET)
        cls.original = {icons.REGISTRY_ASSET:native}
        units = [{'id':13500+n} for n in range(64)]
        registry = icons.registry_patch(units, native); tables = {}
        def tbl(rel): return tables.setdefault(rel, {'asset':generator.DT+rel, 'add':[], 'set':[]})
        for unit in units: icons.add_icon_rows(unit, tbl, generator.row_by)
        for rel in icons.ICON_TABLES: cls.original[generator.DT+rel] = cls.dump(cls.legacy/(generator.DT+rel))
        path = cls.work/'patch.json'
        path.write_text(json.dumps({'legacyRoot':str(cls.legacy), 'outRoot':str(cls.assets),
                                   'tables':[registry, *tables.values()]}), encoding='utf-8')
        cls.dt('patch', path)
        cls.built = {rel:cls.dump(cls.assets/rel) for rel in cls.original}

    @classmethod
    def dt(cls, *args):
        r = subprocess.run([*ffrenv.FFRDT, *map(str,args), '--usmap', str(cls.usmap)],
                           capture_output=True, text=True, encoding='utf-8')
        if r.returncode: raise AssertionError(r.stdout+r.stderr)
        return r.stdout

    @classmethod
    def dump(cls, asset):
        out = cls.work/'dump.json'
        cls.dt('rows', str(asset)+'.uasset', out)
        return json.loads(out.read_text(encoding='utf-8'))['rows']

    def test_sixty_four_tags_and_icon_rows_survive_serialization(self):
        for rel, before in self.original.items():
            after = self.built[rel]
            self.assertEqual(len(after), len(before)+64)
            for key, value in before.items(): self.assertTrue(equivalent(value, after[key]), (rel,key))
        for n in range(64):
            vid = 13500+n; row = f'FFRStudio_Command_{vid}'
            self.assertEqual(self.built[icons.REGISTRY_ASSET][row]['Tag'], icons.command_tag(vid))
            for rel in icons.ICON_TABLES:
                data = self.built[generator.DT+rel][row]
                self.assertEqual(data['Tag']['TagName'], icons.command_tag(vid))
                self.assertEqual(data['Brush']['ResourceObject'], f'ICON_Ability_summon{vid}')

    def test_thirty_two_units_reach_the_table_writer(self):
        if not (ROOT/'build/visions_mod/check/da/DA_UIUnitSsLayout.json').is_file():
            self.skipTest('Prepare the native menu layout first')
        units = []
        for n in range(32):
            vid = 14000+n
            units.append({'key':f'icontest{n}', 'jp':f'IconTest{n}', 'en':f'Icon Test {n}',
                          'id':vid, 'sort':vid, 'donor':13110, 'desc':'Regression fixture',
                          'stats':{'MaxHitPoint':500, 'MaxMagicPoint':100}, 'elemRes':{},
                          'command':{'id':90000+n, 'en':'Skills', 'desc':''},
                          'master':{'id':vid*100, 'en':'Mastery', 'desc':''},
                          'price':1, 'lb':440260, 'attackType':'Physic', 'roles':['eUnitRole::Attacker'],
                          'skills':{}, 'awakening':[[] for _ in range(4)], 'synchro':[[] for _ in range(10)]})
        work = self.work/'prepare32'; real_run = subprocess.run
        class ReachedWriter(Exception): pass
        def stop_at_writer(command, **kwargs):
            if 'patch' in command: raise ReachedWriter()
            return real_run(command, **kwargs)
        with patch.object(generator, 'UNITS', units), patch.object(generator, 'BUILD', str(work)), \
             patch.object(generator, 'OUT', str(work/'assets')), patch.object(sys, 'argv', ['make_vision_mod.py','--no-install']), \
             patch.object(generator.subprocess, 'run', side_effect=stop_at_writer), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ReachedWriter): generator.main()
        recipe = json.loads((work/'patch.json').read_text('utf-8'))
        tables = {t['asset']:t for t in recipe['tables']}
        self.assertEqual(len(tables[icons.REGISTRY_ASSET]['add']), 32)
        commands = tables[generator.DT+'Skill/DT_CommandSkillData']['add']
        self.assertEqual(len(commands), 32)
        self.assertEqual(len({c['set']['SkillIcon.TagName'] for c in commands}), 32)
        for command, unit in zip(commands, units):
            self.assertEqual(command['set']['SkillIcon.TagName'], icons.command_tag(unit['id']))
        for rel in icons.ICON_TABLES:
            self.assertEqual(tables[generator.DT+rel]['set'], [])
            self.assertEqual(len(tables[generator.DT+rel]['add']), 32)

    def test_native_registry_registration_and_composite_parent_references_are_retained(self):
        config = ROOT/'extracted/pak/FFRS/Config/DefaultGameplayTags.ini'
        if config.exists():
            self.assertIn('+GameplayTagTableList=/DebugMenuWidget/Data/GameplayTag/DM_CDT_GamplayTag.DM_CDT_GamplayTag', config.read_text('utf-8'))
        snapshots = []
        for base in (self.legacy, self.assets):
            out = self.work/'full.json'
            log = self.dt('tojson', str(base/icons.REGISTRY_ASSET)+'.uasset', out)
            self.assertIn('roundtrip=True', log)
            data = json.loads(out.read_text(encoding='utf-8'))
            snapshots.append((data['Imports'], data['Exports'][0]['Data']))
        self.assertEqual(snapshots[0], snapshots[1])


if __name__ == '__main__': unittest.main()
