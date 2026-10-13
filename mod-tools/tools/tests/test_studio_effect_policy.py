"""Exercise the shared rules, draft API and build recompile without a game run."""
import sys
from pathlib import Path
from copy import deepcopy
from dataclasses import asdict
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/devui')]
from ability_converter import commands, SourceRecord
from ability_converter.effect_policy import VERSION
import autoport


def source(sid='1', raw=None, kind='ability', **extra):
    return SourceRecord('GL_2024', kind, sid, {'name':'Fixture',
        'effects_raw':raw or [[2,1,1,[0,0,0,0,0,0,500,0]]],
        'attack_frames':[[12]], 'attack_damage':[[100]], 'cost':{'MP':10},
        'icon':'ability_100.png', **extra})


def ability(record):
    return {'id':int(record.id), 'kind':record.kind.upper(), 'name':record.data['name'],
            'sourceRecord':asdict(record), 'icon':record.data['icon']}


def unit():
    return {'key':'policy-fixture','custom':{'schema':1},'id':13500,'jp':'Fixture','ffbe':{'id':'123456789'},
            'skills':{},'awakening':[[],[],[],[]],'synchro':[]}


class StudioPolicyTests(unittest.TestCase):
    def test_shared_opcode_handles_distinct_names_and_eight_light_hits(self):
        for sid, name in [('1','Sunray example'),('2','Another name')]:
            r = source(sid, name=name, element_inflict=['Light'], attack_frames=[[1,2,3,4,5,6,7,8]],
                       attack_damage=[[5,5,5,5,5,5,5,65]])
            p = commands.profile(r, effect_choices={})
            self.assertTrue(p['supported'],p['issues'])
            self.assertEqual(p['set']['hitCount'],8)
            self.assertEqual(p['set']['element'],'Light')
            self.assertEqual(p['conversion']['components'][0]['decision']['key'],'active:1')
            self.assertEqual(p['runtimeValidation'],'not_run')

    def test_mp_regen_default_held_and_explicit_restore_is_one_shot(self):
        r = source(raw=[[2,2,30,[0,0,100,3]]])
        original = deepcopy(r.data)
        p = commands.profile(r, effect_choices={})
        self.assertFalse(p['supported'])
        self.assertIn('reported not working',' '.join(p['issues']))
        p = commands.profile(r, effect_choices={'active:30':'mp_restore'})
        self.assertTrue(p['supported'],p['issues'])
        e = p['conversion']['native']['effects'][0]['set']
        self.assertEqual(e['ParamList'][:4],[5,2,2,-1])
        self.assertEqual((e['applyTiming'],e['proceedTiming'],e['effectEndActionNum']),('AddEffect','AddEffect',1))
        self.assertEqual(r.data,original)
        self.assertEqual(p['snapshot']['records'][0]['data'],original)

    def test_replacement_gate_and_build_recompile(self):
        r = source(raw=[[2,1,40,[0,0,0,0,0,0,0,0,500,500]]])
        u = unit()
        self.assertIsNotNone(autoport.import_entry(u,ability(r),'GLW'))
        self.assertFalse(u['skills'])
        self.assertIsNone(autoport.import_entry(u,ability(r),'GLW',choices={'active:40':'proposed'}))
        s = next(iter(u['skills'].values()))
        self.assertEqual(s['ffbe']['icon'],'ability_100.png')
        self.assertEqual(s['conversionClass'],'replacement')
        self.assertTrue(commands.from_spec(s)['supported'])
        s['effectChoices'] = {}
        self.assertFalse(commands.from_spec(s)['supported'])

    def test_table_only_buff_and_multicast_stay_held(self):
        for raw in ([[0,3,3,[100,0,0,0,3,1]]], [[0,3,97,[2,0,1]]]):
            p = commands.profile(source(raw=raw), effect_choices={})
            self.assertFalse(p['supported'])
            self.assertTrue(p['issues'])
        p = commands.profile(source(raw=[[0,3,32,[5]]],kind='passive',cost={}),effect_choices={})
        self.assertFalse(p['supported'])
        self.assertFalse(p['conversion']['components'][0]['decision']['options'])

    def test_unknown_effect_replacement_retains_cost_restrictions(self):
        p = commands.profile(source(raw=[[2,1,999999,[9]]],cost={'EV':5}),effect_choices={'active:999999':'physical_damage'})
        self.assertFalse(p['supported'])
        self.assertIn('Esper-gauge',' '.join(p['issues']))

    def test_revision_and_kind_identity_do_not_collide(self):
        u = unit()
        for kind in ('ability','magic'):
            r = source(kind=kind)
            self.assertIsNone(autoport.import_entry(u,ability(r),'GLW'))
            self.assertIsNone(autoport.import_entry(u,ability(r),'GLW'))
        self.assertEqual(len(u['skills']),2)

    def test_whole_kit_accounts_for_held_and_capacity_without_duplicates(self):
        u = unit()
        entries = [ability(source(str(i))) for i in range(1,13)]
        entries.append(ability(source('20',raw=[[2,2,30,[0,0,100,3]]])))
        detail = {'region':'GLW','abilities':entries,'passives':[]}
        autoport.autoport(u,detail=detail)
        self.assertEqual((len(u['skills']),len(u['conversionReview'])),(10,3))
        self.assertEqual(sum(r['status']=='loadout_full' for r in u['conversionReview']),2)
        autoport.autoport(u,detail=detail)
        self.assertEqual((len(u['skills']),len(u['conversionReview'])),(10,3))

    def test_old_regen_recipe_is_archived_and_disabled_on_kit_review(self):
        u = unit(); r = source(raw=[[2,2,30,[0,0,100,3]]])
        p = commands.profile(r)
        u['skills']['485000'] = {'mechanics':'converted','conversionSource':p['snapshot'],
            'ffbe':{'id':1,'kind':'ABILITY','source':r.key},'en':'Old refresh'}
        u['awakening'][0] = [['ActiveSkill',485000]]
        autoport.autoport(u,detail={'region':'GLW','abilities':[ability(r)],'passives':[]})
        self.assertFalse(u['skills'])
        self.assertFalse(u['awakening'][0])
        self.assertEqual(u['conversionArchive'][0]['entry']['en'],'Old refresh')
        self.assertEqual(len(u['conversionReview']),1)

    def test_api_returns_disabled_draft_and_never_saves(self):
        from fastapi.testclient import TestClient
        import server
        r = source(raw=[[2,2,30,[0,0,100,3]]]); u = unit()
        with patch.object(server,'save_spec') as save:
            client = TestClient(server.app)
            response = client.post('/api/ffbe/ability/import',json={'unit':u,'ability':ability(r),'region':'GLW'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(response.json()['conversionReview']),1)
            response = client.post('/api/ffbe/ability/import',json={'unit':response.json(),'ability':ability(r),'region':'GLW',
                'effectChoices':{'active:30':'mp_restore'}})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(response.json()['skills']),1)
            self.assertFalse(response.json()['conversionReview'])
            save.assert_not_called()
        self.assertFalse(u['skills'])


if __name__ == '__main__': unittest.main()
