"""Source scene decisions select host adapters without inventing scene changes."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ffbe_effects import scene


class SourceSceneProfile(unittest.TestCase):
    def profile(self, kind, **fields):
        detection={'kind':kind,'referenceStage':[320,320],**fields}
        original=deepcopy(detection)
        profile=scene.default_profile('123','JP/ability/456',detection)
        self.assertEqual(original,detection)
        return profile

    def test_ordinary_and_unresolved_screens_keep_the_existing_battlefield(self):
        for kind in ('screen_overlay','unresolved_screen'):
            with self.subTest(kind=kind):
                profile=self.profile(kind)
                placement=profile['screenPlacement']
                self.assertEqual('camera_plane',placement['mode'])
                self.assertEqual([0,0],placement['sourceOffset'])
                self.assertEqual([320,320],placement['referenceStage'])
                self.assertEqual(profile['export']['runtimeScale'],placement['runtimeScale'])
                self.assertTrue(all(v>=1 for v in placement['overscan']))
                self.assertGreater(placement['cameraDepth']['rearMargin'],0)
                for key in ('backdrop','hideNonParticipants','targetRegistration','camera'):
                    self.assertNotIn(key,placement)
                self.assertNotIn('hostTargetType',profile)

    def test_only_source_replacement_selects_a_background_transition(self):
        profile=self.profile('replacement_background')
        self.assertEqual('native_subspace',profile['screenPlacement']['backdrop'])
        self.assertTrue(profile['preserveSourceColor'])
        self.assertNotIn('camera',profile['screenPlacement'])
        self.assertNotIn('hostTargetType',profile)

    def test_non_screen_effects_do_not_receive_a_camera_adapter(self):
        profile=scene.default_profile('123','JP/ability/456',{'kind':'battlefield'})
        self.assertNotIn('screenPlacement',profile)

    def test_reference_stage_is_copied_not_shared_with_the_detection(self):
        detection={'kind':'screen_overlay','referenceStage':[640,360]}
        profile=scene.default_profile('123','JP/ability/456',detection)
        profile['screenPlacement']['referenceStage'][0]=1
        self.assertEqual([640,360],detection['referenceStage'])


if __name__=='__main__':
    unittest.main()
