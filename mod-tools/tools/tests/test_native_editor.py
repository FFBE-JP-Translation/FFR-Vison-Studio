from copy import deepcopy
from collections import defaultdict
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'tools/devui')]
from tools.tests.test_vision_kits import fixture
import reviewed_kits
import studio_grants
import vision_import
import native_variants
from ability_converter import commands


class NativeEditorTests(unittest.TestCase):
    def test_archived_multicast_uses_prepared_policy_without_runtime_conversion(self):
        u = fixture('401007407')
        p = reviewed_kits.profile('GL_2024/ability/200150',u['ffbe']['id'])
        u['skills']['485000'] = {'mechanics':'converted','effectPolicy':'ffbe-ffr-reviewed/203.1',
            'conversionSource':p['snapshot'],'ffbe':{'source':'GL_2024/ability/200150'}}
        u['awakening'][1].append(['ActiveSkill',485000])
        with patch.object(commands,'profile',side_effect=AssertionError('Reconverted while opening Studio')):
            vision_import.hydrate(u)
        self.assertFalse(u['skills']);self.assertFalse(u['awakening'][1])
        self.assertTrue(u['conversionArchive'])
        self.assertFalse(any(e.get('disabledBy') == 'multicast' for e in u['ffbeLibrary']))

    def test_bundled_vision_import_needs_neither_database_nor_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            with reviewed_kits.connect() as db:
                bundle = reviewed_kits.export_bundle('340000107', db)
            Path(directory, '340000107.json').write_text(json.dumps(bundle), encoding='utf-8')
            with patch.object(reviewed_kits, 'BUNDLES', Path(directory)), patch.object(reviewed_kits, 'PATH', Path(directory)/'missing.sqlite'), patch.object(commands, 'profile', side_effect=AssertionError('Reconverted during import')):
                u = fixture()
                vision_import.hydrate(u)
                self.assertEqual(u['skills'], {})
                vision_import.import_native(u, 'abilities')
                vision_import.import_native(u, 'bonuses')
                expected = {e['sourceKey'] for group in ('abilities','bonuses')
                            for e in native_variants.strongest(deepcopy(bundle['kit']['entries']),group)}
                self.assertEqual(set(u['nativeImports']), expected)
                self.assertEqual(len(u['skills']), 10)
                self.assertTrue(all(len(t) <= 8 for t in u['awakening']))
                saved = deepcopy(u)
                vision_import.import_native(u, 'abilities'); vision_import.import_native(u, 'bonuses')
                self.assertEqual(u, saved)

    def test_2b_import_uses_strongest_upgrades_and_keeps_the_authored_tier(self):
        u = fixture(); u['ffbe']['id'] = '401013807'
        vision_import.hydrate(u)
        base = 'GL_2024/ability/916745'
        vision_import.equip(u, base, target_tier=2)
        u['awakening'][2].insert(0, ['BaseParameter',5,1])
        vision_import.import_native(u, 'abilities')
        sources = {s['ffbe']['source'] for s in u['skills'].values()}
        self.assertEqual(sources, {f'GL_2024/ability/{sid}' for sid in (916753,916755,916758,916759,916768,916818,916742)})
        group,sid = vision_import.imported(u,'GL_2024/ability/916753')
        self.assertEqual(u['awakening'][2][:2], [['BaseParameter',5,1],['ActiveSkill',int(sid)]])
        self.assertTrue(any(a['entry']['ffbe']['source'] == base for a in u['conversionArchive']))
        self.assertTrue(any(e['sourceKey'] == base and e['variantLabel'] == 'Base version' for e in u['ffbeLibrary']))
        self.assertFalse(any(e['componentOf'] and e['sourceKey'] in sources and e['parent'] in sources for e in u['ffbeLibrary']))
        saved = deepcopy(u)
        vision_import.import_native(u,'abilities')
        self.assertEqual(u,saved)

    def test_strongest_compatible_falls_back_without_merging_unrelated_names(self):
        def entry(sid, **extra):
            return {'sourceKey':f'GL_2024/ability/{sid}', 'id':sid, 'kind':'ABILITY',
                    'name':'Move', 'status':'ready', **extra}
        entries = [entry(1),entry(2,replaces='1'),entry(3,replaces=2,status='held'),
                   entry(4,origin='linked',parent='GL_2024/ability/2'),entry(5),
                   entry(6,name='Bonus',kind='PASSIVE')]
        self.assertEqual([e['id'] for e in native_variants.strongest(entries,'abilities')],[2,5])
        self.assertEqual([e['id'] for e in native_variants.strongest(entries,'bonuses')],[6])

    def test_pending_edits_survive_assignment_removal_and_reassignment(self):
        u = fixture(); vision_import.import_native(u, 'abilities')
        entry = next(e for e in u['ffbeLibrary'] if e['kind'] == 'ABILITY' and e['status'] == 'ready' and not vision_import.imported(u,e['sourceKey']))
        ref = {'sourceKey': entry['sourceKey']}
        edits = {'name': 'Edited move', 'description': 'User description', 'cost': 7, 'icon': 'UI.Skill.Action.Icon.Fire'}
        studio_grants.edit(u, ref, edits)
        first = next((t,i) for t,tier in enumerate(u['awakening']) for i,g in enumerate(tier) if g[0] == 'ActiveSkill')
        studio_grants.action(u, {'action':'remove','tier':first[0],'index':first[1]})
        studio_grants.action(u, {'action':'assign', 'sourceKey':entry['sourceKey'], 'tier':2, 'index':0})
        group,sid = vision_import.imported(u, entry['sourceKey'])
        recipe = u[group][sid]
        self.assertEqual(u['awakening'][2][0], ['ActiveSkill',int(sid)])
        self.assertEqual((recipe['en'],recipe['desc'],recipe['set']['Cost']), ('Edited move','User description',7))
        self.assertEqual(recipe['set']['SkillIcon.TagName'], edits['icon'])
        studio_grants.action(u, {'action':'remove','tier':2,'index':0})
        vision_import.equip(u, entry['sourceKey'], target_tier=1)
        group,sid = vision_import.imported(u, entry['sourceKey'])
        self.assertEqual(u[group][sid]['set']['Cost'],7)
        # Editing this vision must not alter its cached prepared source profile.
        self.assertNotEqual(reviewed_kits.profile(entry['sourceKey'],u['ffbe']['id'])['set']['Cost'],7)

    def test_stock_edits_clone_just_this_visions_row(self):
        u = fixture(); original = studio_grants.ffr_catalog.load()
        for kind, rows, group in [('ActiveSkill',original['skills'],'skills'), ('PassiveSkill',original['passives'],'convertedPassives')]:
            row = next(r for r in rows if r['id'] > 0)
            saved = deepcopy(row)
            u['awakening'][0].append([kind,row['id']])
            studio_grants.edit(u, {'kind':kind,'id':row['id']}, {'name':'Local name','description':'Local description','icon':'UI.Skill.Action.Icon.Fire','cost':4})
            self.assertEqual(row,saved)
            self.assertNotIn([kind,row['id']],u['awakening'][0])
            self.assertTrue(any(s['from']==row['id'] and s['en']=='Local name' for s in u[group].values()))

    def test_passive_name_description_icon_and_cost_reach_native_tables(self):
        import make_vision_mod as builder
        u = fixture(); vision_import.import_native(u,'bonuses')
        sid, spec = next(iter(u['convertedPassives'].items()))
        edits = {'name':'Bright recovery','description':'Edited bonus text','cost':3,'icon':'UI.Skill.Action.Icon.Light'}
        studio_grants.edit(u, {'kind':'PassiveSkill','id':int(sid)}, edits)
        tables = defaultdict(lambda:{'add':[],'set':[]})
        builder.prepare_converted_passives(u, lambda t:tables[t])
        row = next(r['set'] for r in tables['Skill/DT_PassiveSkillData']['add'] if r['set']['ID'] == int(sid))
        self.assertEqual(row['Name'],edits['name'])
        self.assertEqual(row['Description'],builder.text(edits['description']))
        self.assertEqual(row['equipCost'],3)
        self.assertEqual(row['SkillIcon.TagName'],edits['icon'])

    def test_api_edit_and_import_are_drafts_with_validation(self):
        from fastapi.testclient import TestClient
        import server
        client = TestClient(server.app); u=fixture()
        with patch.object(server,'save_spec') as save:
            response=client.post('/api/studio/grants',json={'unit':u,'action':'import','group':'abilities'})
            self.assertEqual(response.status_code,200,response.text)
            draft=response.json(); key=draft['ffbeLibrary'][0]['sourceKey']
            response=client.post('/api/studio/grants',json={'unit':draft,'action':'edit','ref':{'sourceKey':key},'edits':{'name':'Invalid','description':'','cost':-1,'icon':''}})
            self.assertEqual(response.status_code,422)
            self.assertFalse(u['skills']);save.assert_not_called()

    def test_active_edits_reach_native_command_tables(self):
        import make_vision_mod as builder
        unit = fixture()
        vision_import.import_native(unit, 'abilities')
        sid, recipe = next(iter(unit['skills'].items()))
        studio_grants.edit(unit, {'kind':'ActiveSkill','id':int(sid)},
            {'name':'Edited strike','description':'A custom description.','cost':7,'icon':'UI.Skill.Action.Icon.Fire'})
        unit['ffbe']['dir'] = str(ROOT/'data/ffbe/sprites/340000107')
        unit['command'] = {'id':320}
        tables = defaultdict(lambda:{'add':[],'set':[]})
        builder.prepare_converted_command(unit, recipe, int(sid), lambda t:tables[t], [], [])
        settings = next(r['set'] for r in tables['Skill/DT_SkillData']['add'] if r['set']['ID'] == int(sid))
        self.assertEqual(settings['Cost'],7)
        self.assertEqual(settings['Name'],builder.text('Edited strike'))
        self.assertEqual(settings['Description'],builder.text('A custom description.'))
        self.assertEqual(settings['SkillIcon.TagName'],'UI.Skill.Action.Icon.Fire')

    def test_add_vision_equips_native_abilities_and_bonuses_evenly(self):
        from fastapi.testclient import TestClient
        import server
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.object(server.unit_downloads,'ensure_selection'))
            stack.enter_context(patch.object(server.ffbe_catalog,'unit_detail',return_value={'id':'340000107','name':'Fixture','region':'GL'}))
            stack.enter_context(patch.object(server.ffbe_catalog,'shift_info',return_value=None))
            stack.enter_context(patch.object(server.ffbe_catalog,'index_rows',return_value={}))
            stack.enter_context(patch.object(server.dump_ffbe_unit,'dump'))
            stack.enter_context(patch.object(server,'default_spec',return_value=fixture()))
            stack.enter_context(patch.object(server,'load_spec',return_value=[]))
            save=stack.enter_context(patch.object(server,'save_spec'))
            response=TestClient(server.app).post('/api/spec/add',json={'ffbeId':'340000107','form':'340000107','autoport':False})
            self.assertEqual(response.status_code,200,response.text)
            unit=response.json()
            self.assertTrue(unit['ffbeLibrary'])
            self.assertEqual(len(unit['skills']),10)
            self.assertEqual(len(unit['convertedPassives']),8)
            self.assertTrue(unit['fullKit'])
            self.assertEqual([len(t) for t in unit['awakening']],[5,5,4,4])
            self.assertEqual(save.call_args.args[0][0]['ffbeLibrary'],unit['ffbeLibrary'])

    def test_large_default_kit_keeps_every_supported_family_and_defers_media(self):
        unit=fixture('100047707')
        vision_import.hydrate(unit)
        import effect_downloads
        with patch.object(effect_downloads,'ensure_move') as media:
            vision_import.initialize_native_loadout(unit)
            media.assert_not_called()
        expected={e['sourceKey'] for group in ('abilities','bonuses')
                  for e in native_variants.strongest(unit['ffbeLibrary'],group) if e['status']=='ready'}
        actual={recipe['ffbe']['source'] for group in ('skills','convertedPassives') for recipe in unit[group].values()}
        self.assertEqual(actual,expected)
        self.assertEqual(len(unit['skills']),48)
        self.assertTrue(all(recipe['fullKitSequence'] for recipe in unit['skills'].values()))
        for kind in ('ActiveSkill','PassiveSkill',None):
            counts=[sum(kind is None or grant[0]==kind for grant in tier) for tier in unit['awakening']]
            self.assertLessEqual(max(counts)-min(counts),1)
        locations={tuple(g):tier for tier,grants in enumerate(unit['awakening']) for g in grants}
        self.assertTrue(all(v['tier']==locations[tuple(v['grant'])] for v in unit['ffbeMap']['passives'].values()))
        # Reopening or re-running initialization must preserve manual tier edits.
        unit['awakening'][3].append(unit['awakening'][0].pop())
        saved=deepcopy(unit)
        vision_import.hydrate(unit)
        vision_import.initialize_native_loadout(unit)
        self.assertEqual(unit,saved)

    def test_highest_plus_five_is_selected_for_abilities_and_bonuses(self):
        entries=[]
        for kind in ('ABILITY','PASSIVE'):
            for level in range(6):
                entries.append({'sourceKey':f'GL/{kind}/{level}', 'id':f'{kind}{level}',
                    'kind':kind,'name':f'Move +{level}','status':'ready',
                    'replaces':f'{kind}{level-1}' if level else None})
        for group,kind in (('abilities','ABILITY'),('bonuses','PASSIVE')):
            self.assertEqual([e['sourceKey'] for e in native_variants.strongest(entries,group)],[f'GL/{kind}/5'])


if __name__ == '__main__': unittest.main()
