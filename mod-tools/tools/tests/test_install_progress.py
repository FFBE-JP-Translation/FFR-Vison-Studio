from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'devui')]
import server


class InstallProgressTests(unittest.TestCase):
    def test_install_last_reports_live_stage_and_finishes(self):
        with patch.object(server, 'state', {'running': False}):
            def install(log):
                self.assertTrue(server.state['running'])
                log('##stage Refreshing the Mitra battle NPC (2 of 3)')
                self.assertEqual(server.build_log()['stage'], 'Refreshing the Mitra battle NPC (2 of 3)')
                return {'files': 12, 'backup': 'test'}
            with patch.object(server, 'install_files', side_effect=install):
                self.assertTrue(server.install_only()['ok'])
            self.assertFalse(server.state['running'])
            self.assertGreaterEqual(server.state['finished'], server.state['started'])

    def test_failed_install_leaves_failure_visible_and_releases_running_state(self):
        with patch.object(server, 'state', {'running': False}), patch.object(server, 'install_files', side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(server.HTTPException): server.install_only()
            self.assertFalse(server.state['running'])
            self.assertEqual(server.state['result'], 'failed')
            self.assertIn('fixture failure', server.state['message'])

    def test_install_last_cannot_overlap_a_build(self):
        with patch.object(server, 'state', {'running': True}), patch.object(server, 'install_files') as install:
            with self.assertRaises(server.HTTPException): server.install_only()
            install.assert_not_called()


if __name__ == '__main__': unittest.main()
