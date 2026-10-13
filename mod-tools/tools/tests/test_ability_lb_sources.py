"""Linked LBs survive source capture, source isolation and saved-profile reload."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/devui')]
import ffbe_lb as lb
from ability_converter import SourceRecord
from ability_converter.lb_sources import FolderResolver,attach
from ability_converter.resonance import profile,source_record
from ability_converter.catalog import SourceCatalog


def source(opcode=132,params=None):
    return {'schema':2,'unitId':'123','fps':60,'lbId':'7','availableLbIds':['7'],
        'name':'Future ward','moveType':0,'elements':[],'rawAttackFrames':'24:100','rawLb':{'cost':25},
        'components':[{'index':0,'range':0,'target':3,'type':opcode,'params':params or [8,0,2,100,0,9]}]}


def ward(sid='8',**extra):
    return SourceRecord('GL_2024','ability',sid,{'name':'Self ward','mp_cost':0,
        'effects_raw':[[0,3,3,[100,0,0,0,2,1]]],'attack_frames':[[90]],'attack_damage':[[100]],**extra})


def captured(src=None,children=None,**extra):
    src=src or source();root=replace(source_record(src),source='GL_2024',level='1')
    root.data.update(extra)
    with SourceCatalog() as catalog:
        catalog.add(root)
        for child in children or [ward()]:catalog.add(child)
        catalog.finish()
        return attach(src,root,catalog)


class LinkedSourceTests(unittest.TestCase):
    def test_packaged_lb_recompiles_children_without_developer_sources(self):
        from release.build_release import ship_converter_data
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            engine=Path(directory);ship_converter_data(str(engine/'data'))
            shutil.copytree(ROOT/'tools/ability_converter',engine/'tools/ability_converter',
                            ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            shutil.copyfile(ROOT/'tools/ffbe_lb.py',engine/'tools/ffbe_lb.py')
            (engine/'source.json').write_text(json.dumps(captured()),encoding='utf8')
            script="""import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ability_converter.resonance import profile,converter
from ability_converter.compiler import TableWriter
source=json.loads(Path('source.json').read_text(encoding='utf8'))
timeline,p=profile(source)
assert p['supported'],p['issues']
writer=TableWriter(converter().native);writer.add(p['conversion'])
assert len(writer.tables['Skill/DT_SkillData']['add'])==2
assert timeline['hitFrames']==[24]
print('portable delayed LB passed')
"""
            completed=subprocess.run([sys.executable,'-I','-B','-c',script,str(engine/'tools')],
                cwd=engine,capture_output=True,text=True,encoding='utf8')
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertIn('portable delayed LB passed',completed.stdout)

    def test_saved_profile_reloads_without_source_files(self):
        src=captured()
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            path=Path(directory)/'lb.json';path.write_text(json.dumps(src),encoding='utf8')
            with patch.object(lb,'table',side_effect=AssertionError('No master lookup')):
                saved=lb.resolve({'ffbe':{'id':'123'}},{'ffbe_lb':str(path)})
                timeline,result=profile(saved)
        self.assertTrue(result['supported'],result['issues'])
        self.assertEqual(timeline['hitFrames'],[24])
        self.assertEqual(result['conversion']['source']['key'],'GL_2024/lb/7/level/1')
        self.assertEqual(result['conversion']['costs']['lb_cost'],25)
        self.assertEqual(len(src['conversionSource']['records']),2)

    def test_snapshot_and_presentation_must_describe_same_mechanics(self):
        src=captured()
        mutations=(lambda s:s.update(lbId='70'),
            lambda s:s.update(rawAttackFrames='25:100'),lambda s:s.update(elements=['Fire']),
            lambda s:s['components'][0]['params'].__setitem__(2,3),
            lambda s:s['rawLb'].update(cost=40))
        for mutate in mutations:
            changed=deepcopy(src);mutate(changed)
            with self.subTest(changed=changed['lbId']):
                _,p=profile(changed);self.assertFalse(p['supported']);self.assertIn('snapshot mechanics',' '.join(p['issues']))

    def test_missing_or_foreign_child_never_uses_a_fallback(self):
        src=captured()
        for change in ('missing','foreign'):
            altered=deepcopy(src)
            if change=='missing':altered['conversionSource']['records'].pop()
            else:altered['conversionSource']['records'][1]['source']='JP_2024'
            _,p=profile(altered);self.assertFalse(p['supported']);self.assertNotIn('fallback',p)
            self.assertIn('Missing snapshot reference',' '.join(p['conversion']['components'][0]['issues']))

    def test_root_restrictions_remain_in_snapshot(self):
        _,p=profile(captured(equip_requirement=['sword']))
        self.assertFalse(p['supported']);self.assertIn('equip_requirement',' '.join(p['issues']))

    def test_capture_keeps_canonical_compound_vectors_over_presentation_text(self):
        src=source(100,['8&9',1])
        root=replace(source_record(src),source='JP_CLIENT')
        root.data['effects_raw']=[[0,3,100,[[8,9],1]]]
        with SourceCatalog() as catalog:
            catalog.add(root);catalog.finish();saved=attach(src,root,catalog)
        self.assertEqual(saved['components'][0]['params'],[[8,9],1])
        self.assertEqual(saved['conversionSource']['records'][0]['data']['effects_raw'],root.data['effects_raw'])
        self.assertEqual(src['components'][0]['params'],['8&9',1])
        _,p=profile(saved);self.assertFalse(p['supported'])

    def test_child_cost_and_nested_restrictions_remain_held(self):
        for child in (ward(mp_cost=5),ward(effects_raw=[[0,3,130,[9,0,2,1]]])):
            _,p=profile(captured(children=[child]));self.assertFalse(p['supported'])

    def test_immediate_support_uses_child_frame(self):
        timeline,p=profile(captured(source(71,[8,1])))
        self.assertTrue(p['supported'],p['issues']);self.assertEqual(timeline['hitFrames'],[90])

    def test_immediate_damage_keeps_long_child_sequence_and_lb_budget(self):
        child=ward(effects_raw=[[2,1,1,[0,0,0,0,0,0,1000]]],
                   attack_frames=[list(range(48))],attack_damage=[[1]*47+[53]])
        timeline,p=profile(captured(source(71,[8,1]),[child]))
        self.assertTrue(p['supported'],p['issues']);self.assertEqual(timeline['hitFrames'],list(range(48)))
        self.assertAlmostEqual(sum(timeline['hitPercents']),100)
        self.assertEqual(p['binding']['gaugePolicy'],'native_finish_blow')

    def test_nested_delayed_chains_are_captured_and_cycles_are_held(self):
        child=ward(effects_raw=[[0,3,132,[9,0,1,100,0,1]]])
        src=captured(children=[child,ward('9')]);_,p=profile(src)
        self.assertTrue(p['supported'],p['issues']);self.assertEqual(len(src['conversionSource']['records']),3)
        cyclic=ward('9',effects_raw=[[0,3,132,[8,0,1,100,0,1]]])
        _,p=profile(captured(children=[child,cyclic]));self.assertFalse(p['supported'])

    def test_datamine_loader_captures_actual_selected_revision_and_level(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            folder=Path(directory);(folder/'skills.json').write_text(json.dumps({'8':ward().data}),encoding='utf8')
            burst={'name':'Future ward','move_type':0,'attack_frames':[[24]],'attack_damage':[[100]],
                'levels':{'2':{'cost':25,'effects_raw':[[0,3,132,[8,0,2,100,0,9]]]},
                          '5':{'cost':40,'effects_raw':[[0,3,999999,[]]]}}}
            with patch.object(lb,'datamine',return_value=({'123':{'limitburst_id':[7]}},{'7':burst},directory)),patch.object(lb,'table',return_value={'rows':[],'file':'fixture'}):
                src=lb.from_datamine({'ffbe':{'id':'123','source':'GLW'}},{})
        _,p=profile(src);self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(src['conversionSource']['root'],'GL_2024/lb/7/level/2')
        self.assertEqual(src['rawLb']['cost'],25)

    def test_folder_resolver_does_not_fall_back_across_source_directories(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            root=Path(directory);gl=root/'gl';jp=root/'jp';gl.mkdir();jp.mkdir()
            (gl/'skills.json').write_text('{}',encoding='utf8')
            (jp/'skills.json').write_text(json.dumps({'8':ward().data}),encoding='utf8')
            resolver=FolderResolver(gl,'GL_2024')
            with self.assertRaisesRegex(ValueError,'Missing linked LB skill'):
                resolver.resolve({'source':'GL_2024','kind':'lb'},{'id':'8','kind':'skill'})
            with self.assertRaisesRegex(ValueError,'selected source revision'):
                resolver.resolve({'source':'JP_2024','kind':'lb'},{'id':'8','kind':'skill'})

    def test_master_resolver_retains_magic_and_rejects_ambiguous_ids(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            folder=Path(directory);magic={'magic_id':'8','effect_type':'3','effect_param':'100,0,0,0,2,1',
                'target':'3','target_range':'0','attack_frames':'90:100','mp_cost':0}
            (folder/'F_MAGIC_MST.json').write_text(json.dumps({'rows':[magic]}),encoding='utf8')
            resolver=FolderResolver(folder,'JP_CLIENT',master=True);identity={'source':'JP_CLIENT','kind':'lb'};dependency={'id':'8','kind':'skill'}
            child=resolver.resolve(identity,dependency);self.assertEqual(child.kind,'magic')
            (folder/'F_ABILITY_MST.json').write_text(json.dumps({'rows':[{**magic,'ability_id':'8'}]}),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'Ambiguous'):resolver.resolve(identity,dependency)

    def test_master_lb_loader_captures_child_from_its_own_directory(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'build') as directory:
            folder=Path(directory)
            child={'magic_id':'8','effect_type':'3','effect_param':'100,0,0,0,2,1',
                'target':'3','target_range':'0','attack_frames':'90:100','mp_cost':0}
            (folder/'F_MAGIC_MST.json').write_text(json.dumps({'rows':[child]}),encoding='utf8')
            tables={'F_UNIT_MST':[{'unit_evo_id':'123','lb_id':'7'}],
                'F_LIMITBURST_MST':[{'lb_id':'7','effect_type':'132','effect_param':'8,0,2,100,0,9',
                'target':'3','target_range':'0','attack_frames':'24:100','cost':25}], 'F_EFFECT_GROUP_MST':[]}
            with patch.object(lb,'table',side_effect=lambda n:{'rows':tables[n],'file':n,'_directory':directory}):
                src=lb.resolve({'ffbe':{'id':'123','source':'JP'}},{})
        _,p=profile(src);self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(src['conversionSource']['root'],'JP_CLIENT/lb/7')
        self.assertEqual(src['conversionSource']['records'][1]['kind'],'magic')

    def test_uncaptured_link_stays_held(self):
        _,p=profile(source());self.assertFalse(p['supported']);self.assertIn('source catalog',' '.join(p['issues']))


if __name__=='__main__':unittest.main()
