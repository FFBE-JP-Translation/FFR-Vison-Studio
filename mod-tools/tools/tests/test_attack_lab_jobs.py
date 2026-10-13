"""Job boundaries and installation recovery, without touching the game."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import shutil
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/devui')]
import attack_lab as lab


class AttackLabJobs(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.folder=self.root/'job'; self.folder.mkdir()
        self.game=self.root/'game'; self.game.mkdir()
        self.host=SimpleNamespace(game_running=lambda:False,state={'running':False})
        for target,value in (('ROOT',self.root),('WORK',self.root/'work'),('host',self.host),
                             ('job',{'running':False,'stage':'Starting','log':[]})):
            context=patch.object(lab,target,value); context.start(); self.addCleanup(context.stop)
        context=patch.object(lab.ffrenv,'game_paks',return_value=str(self.game)); context.start(); self.addCleanup(context.stop)
        self.out=self.root/'build/out'; self.out.mkdir(parents=True)
        self.destination=self.game/'~mods'; self.destination.mkdir()
        for ext in ('pak','utoc','ucas'):
            (self.out/f'{lab.STEM}.{ext}').write_bytes(('new '+ext).encode())
            (self.destination/f'{lab.STEM}.{ext}').write_bytes(('old '+ext).encode())
        (self.destination/'another-mod.pak').write_bytes(b'untouched')

    def test_install_records_backups_and_preserves_other_mods(self):
        lab.install(self.folder)
        for ext in ('pak','utoc','ucas'):
            name=f'{lab.STEM}.{ext}'
            self.assertEqual((self.destination/name).read_bytes(),('new '+ext).encode())
            self.assertEqual((self.folder/'previous-install'/name).read_bytes(),('old '+ext).encode())
        self.assertEqual((self.destination/'another-mod.pak').read_bytes(),b'untouched')
        self.assertEqual(len(json.loads((self.folder/'installation.json').read_text())['files']),3)

    def test_failed_install_restores_replaced_files(self):
        copy=shutil.copy2
        def interrupted(source,destination,*args,**kwargs):
            if Path(source)==self.out/f'{lab.STEM}.utoc': raise OSError('test disk error')
            return copy(source,destination,*args,**kwargs)
        with patch.object(lab.shutil,'copy2',side_effect=interrupted), self.assertRaises(OSError): lab.install(self.folder)
        for ext in ('pak','utoc','ucas'):
            self.assertEqual((self.destination/f'{lab.STEM}.{ext}').read_bytes(),('old '+ext).encode())

    def test_build_all_invokes_catalog_with_resume_and_frozen_settings(self):
        document={'schema':'ffr-attack-director-1','defaults':{'castZoom':1.6},'moves':{}}
        with patch.object(lab,'process') as invoke:
            lab.run({'scope':'all'},self.folder,document)
        command,env=invoke.call_args.args
        self.assertIn('--catalog',command); self.assertIn('--resume',command); self.assertNotIn('--move',command)
        self.assertEqual(json.loads(Path(env['FFR_ATTACK_SETTINGS']).read_text()),document)
        self.assertEqual(lab.job['result'],'complete'); self.assertFalse(lab.job['running'])

    def test_newly_prepared_selected_move_is_discoverable(self):
        form='100032707'; key='GL_2024/ability/1'
        output=lab.WORK/'selected'; output.mkdir(parents=True)
        entry={'sourceKey':key,'visuals':[]}
        (output/f'{form}.json').write_text(json.dumps({'moves':{key:entry}}))
        self.assertEqual(lab.prepared(form,key),(entry,output/f'{form}.json'))


if __name__=='__main__': unittest.main()
