"""Addon preparation leaves live packs alone and detects concurrent changes."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/devui')]
import addon_install as install
sys.path.insert(0, str(ROOT/'tools/private'))
import verify_vision_install as verify_install


class AddonInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.paks=self.root/'live/FFRS/Content/Paks'
        self.mods=self.paks/'~mods';self.mods.mkdir(parents=True)
        (self.paks/'FFRS-Windows.utoc').write_bytes(b'base')
        self.script=self.root/'tools/private';self.script.mkdir(parents=True)
        for stem,script,_ in install.ADDONS:
            (self.script/script).touch()
            for ext in ('.utoc','.ucas','.pak'): (self.mods/(stem+ext)).write_bytes(b'old '+stem.encode())
        self.source=self.root/'new.utoc';self.source.write_bytes(b'new vision')
        self.calls=[]
        for obj,key,value in [(install.ffrenv,'ROOT',str(self.root)),(install.ffrenv,'game_running',lambda:False)]:
            p=patch.object(obj,key,value);p.start();self.addCleanup(p.stop)

    def build(self, command, log):
        self.calls.append(command)
        game=Path(command[command.index('--game')+1]);mods=game/'FFRS/Content/Paks/~mods'
        self.assertEqual((mods/'Studio.utoc').read_bytes(),b'new vision')
        if any('make_npc_battles' in s for s in command):
            self.assertEqual((mods/'zzzz_PrivateParty_2_P.utoc').read_bytes(),b'rebuilt')
        for stem,script,_ in install.ADDONS:
            if any(script in s for s in command):
                for ext in ('.utoc','.ucas','.pak'): (mods/(stem+ext)).write_bytes(b'rebuilt')

    def test_stages_party_then_npc_then_verifies_without_changing_live_game(self):
        before=install.snapshot(self.mods)
        with patch.object(install,'run',side_effect=self.build):
            outputs,work=install.prepare(self.paks,{'Studio.utoc':self.source},lambda _:None)
        self.assertEqual(len(outputs),9);self.assertEqual(len(self.calls),4)
        self.assertIn('--keep-saves',self.calls[0])
        self.assertEqual(install.snapshot(self.mods),before)
        self.assertTrue((Path(work)/'prepared.json').is_file())

    def test_failed_build_leaves_live_addons_intact(self):
        before=install.snapshot(self.mods)
        with patch.object(install,'run',side_effect=RuntimeError('failed')):
            with self.assertRaisesRegex(RuntimeError,'failed'):
                install.prepare(self.paks,{'Studio.utoc':self.source},lambda _:None)
        self.assertEqual(install.snapshot(self.mods),before)

    def test_concurrent_mod_change_blocks_installation(self):
        def change(command, log):
            self.build(command,log)
            (self.mods/'new-user-mod.pak').write_bytes(b'user')
        with patch.object(install,'run',side_effect=change):
            with self.assertRaisesRegex(RuntimeError,'changed during preparation'):
                install.prepare(self.paks,{'Studio.utoc':self.source},lambda _:None)


class InstalledLimitBurstTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.unit = {'id':13503, 'en':'Rain & Fina', 'command':{'id':323},
                     'ffbe':{'id':'100032707'}, 'lb_custom':{'presentation':'ffbe'},
                     'skills':{}, 'awakening':[[], [], [], []]}
        self.path = '/Game/Sequencer/Battle/Skill/444040/444041/SEQ_Battle_444041_Master'
        self.tables = {
            'Skill/DT_SkillData': {'LB':{'ID':444040}},
            'Skill/DT_PassiveSkillData': {}, 'Skill/DT_SkillEffectData': {},
            'Skill/DT_CommandSkillData': {'Command':{'ID':323,'unitIdToUseSkill':13503}},
            'Item/Vision/DT_VisionItemData': {'Vision':{'ID':13503,'finishBlowSkill':444040}},
            'Item/Vision/DT_VisionAwakeningMasteryData': {},
            'Asset/Skill/DT_SkillAsset': {str(sid):{'ID':sid,'LevelSequence':{
                'AssetPathName':self.path+'.SEQ_Battle_444041_Master','SubPathString':''}}
                for sid in (444041,444042)},
            'Skill/Other/DT_SkillGeneralData': {'General':{'equipperActionVisionSkills':[]}},
            'Battle/Sequencer/DT_BtlHitEffectData': {}, 'UI/Skill/CDT_SkillIcon': {}}
        self.packages = {self.path:{'Type':'LevelSequence'}}
        self.loaded = []

    def read(self, paks, path, output):
        self.assertEqual(paks, self.work/'staged/FFRS/Content/Paks')
        if path.startswith('/Game/Datatable/'):
            return {'Rows':self.tables[path.removeprefix('/Game/Datatable/')]}
        self.loaded.append(path)
        if path not in self.packages:
            raise RuntimeError('Package absent from effective mounted containers')
        return self.packages[path]

    def verify(self):
        with patch.object(verify_install, 'export_json', side_effect=self.read):
            return verify_install.verify(self.work/'staged/FFRS/Content/Paks',
                                         [self.unit], self.work/'readback')

    def test_zero_ordinary_skills_still_verifies_lb_and_both_variants(self):
        result = self.verify()[0]
        self.assertEqual(0, result['abilities'])
        self.assertEqual({'id':444040,'sequenceIds':[444041,444042],
                          'packagedSequences':[self.path]}, result['limitBurst'])
        self.assertEqual([self.path], self.loaded)  # Shared Master is loaded once.

    def test_overridden_finish_blow_and_missing_skill_fail(self):
        self.tables['Item/Vision/DT_VisionItemData']['Vision']['finishBlowSkill'] = 440110
        with self.assertRaisesRegex(ValueError, 'finishBlowSkill'):
            self.verify()
        self.tables['Item/Vision/DT_VisionItemData']['Vision']['finishBlowSkill'] = 444040
        self.tables['Skill/DT_SkillData'].clear()
        with self.assertRaisesRegex(ValueError, 'custom LB skill 444040 is missing'):
            self.verify()

    def test_missing_group_variant_and_wrong_move_reference_fail(self):
        variants = self.tables['Asset/Skill/DT_SkillAsset']
        group = variants.pop('444042')
        with self.assertRaisesRegex(ValueError, 'sequence variants'):
            self.verify()
        variants['444042'] = group
        variants['444042']['LevelSequence']['AssetPathName'] = '/Game/Other/Donor.Donor'
        with self.assertRaisesRegex(ValueError, 'points to another move'):
            self.verify()

    def test_unmounted_or_wrong_type_package_fails_despite_table_reference(self):
        self.packages.clear()
        with self.assertRaisesRegex(ValueError, 'not readable from installed packages'):
            self.verify()
        self.packages[self.path] = {'Type':'Texture2D'}
        with self.assertRaisesRegex(ValueError, 'not a packaged LevelSequence'):
            self.verify()

    def test_unit_without_custom_lb_keeps_existing_checks(self):
        del self.unit['lb_custom']
        self.tables['Skill/DT_SkillData'].clear()
        self.packages.clear()
        result = self.verify()[0]
        self.assertNotIn('limitBurst', result)
        self.assertEqual([], self.loaded)


if __name__=='__main__': unittest.main()
