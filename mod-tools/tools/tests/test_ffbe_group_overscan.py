"""Host NV-overlay overscan must never change the cached source simulation."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TOOLS), str(TOOLS/'ffbe_effects'), str(TOOLS/'devui')]
from prepare_vision import compose, resolve_screen_group_overscan


PLACEMENT = {'mode': 'frozen_caster_plane', 'sourceOffset': [-96, 84]}
CONFIG = {'groupIds': ['5040290', '5040295'], 'scale': 1.2}


def sprite(x, y, blend='add'):
    return {'tex': 0, 'uv': [0, 0, 64, 64], 'pos': [x, y], 'scale': [2.4, -1.2],
            'rot': 25., 'alpha': .75, 'color': [.3, .6, .9], 'blend': blend,
            'flipX': False, 'flipY': True}


def spawn(group, file, anchor='screen', frame=0):
    return {'groupId': group, 'file': file, 'anchor': anchor, 'frame': frame,
            'scale': 1.1, 'rotation': [0, 0, 0], 'x': 0, 'y': 0}


class ScreenGroupOverscan(unittest.TestCase):
    def test_only_selected_nv_groups_change_and_cached_inputs_stay_exact(self):
        spawns = [spawn('8008450', 'nebula'), spawn('8008451', 'front_center'),
                  spawn('8008452', 'caster', 'caster'), spawn('5040290', 'streaks'),
                  spawn('5040295', 'frame')]
        docs = {s['file']: {'textures': [s['file']+'.png'], 'frames': [[sprite(12., -24.)]]}
                for s in spawns}
        before = deepcopy((spawns, docs))
        scales = resolve_screen_group_overscan(CONFIG, spawns, PLACEMENT)
        first, old = compose(spawns, docs)
        current_first, new = compose(spawns, docs, scales)
        self.assertEqual(first, current_first)
        self.assertEqual(old['textures'], new['textures'])
        self.assertEqual(old['frameCount'], new['frameCount'])
        for i, (a, b) in enumerate(zip(old['frames'][2], new['frames'][2], strict=True)):
            if i < 3:
                self.assertEqual(a, b)  # Nebula, actual front_center, and caster.
            else:
                self.assertEqual([v*1.2 for v in a['pos']], b['pos'])
                self.assertEqual([v*1.2 for v in a['scale']], b['scale'])
                self.assertEqual({k:v for k,v in a.items() if k not in ('pos','scale')},
                                 {k:v for k,v in b.items() if k not in ('pos','scale')})
        self.assertEqual(before, (spawns, docs))
        self.assertEqual({'5040290', '5040295'}, set(new['groupTransforms']))

    def test_source_bar_expands_about_screen_offset_not_the_caster(self):
        s = spawn('5040295', 'frame')
        # The source left NV border center is (-160,-15), and group scale is1.1.
        docs = {'frame': {'textures': ['frame.png'], 'frames': [[sprite(-160*2.4, -15*2.4)]]}}
        _, doc = compose([s], docs, {'5040295': 1.2})
        x,y = [v/doc['pixelsPerUnit'] for v in doc['frames'][2][0]['pos']]
        self.assertAlmostEqual(-307.2, x + PLACEMENT['sourceOffset'][0])
        self.assertAlmostEqual(64.2, y + PLACEMENT['sourceOffset'][1])
        # Applying overscan after translating around the caster would give
        # -326.4 and81; both would incorrectly move the shared screen center.

    def test_audit_tracks_source_ordinal_even_when_parts_change_group(self):
        spawns = [spawn('8008451', 'main'), spawn('5040295', 'frame')]
        docs = {'main': {'textures': ['main.png'], 'frames': [[sprite(1,2)], [], [sprite(3,4)]]},
                'frame': {'textures': ['frame.png'], 'frames': [[sprite(5,6)]]*3}}
        _, doc = compose(spawns, docs, {'5040295':1.2})
        self.assertEqual({'add_1':[2,4], 'add_0':[3]}, doc['groupTransforms']['5040295']['parts'])
        self.assertEqual([2,1,2], [len(f) for f in doc['frames'][2:5]])

    def test_invalid_or_mistargeted_overrides_fail_closed(self):
        spawns = [spawn('5040290','streaks'), spawn('5040295','frame')]
        invalid = [None, True, 0., .9, float('nan'), float('inf')]
        for value in invalid:
            with self.subTest(scale=value), self.assertRaises(ValueError):
                resolve_screen_group_overscan({**CONFIG,'scale':value}, spawns, PLACEMENT)
        for ids in ([], ['missing'], ['5040295','5040295'], ['99999999'], [5040295]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                resolve_screen_group_overscan({**CONFIG,'groupIds':ids}, spawns, PLACEMENT)
        with self.assertRaises(ValueError):
            resolve_screen_group_overscan({**CONFIG,'extra':True}, spawns, PLACEMENT)
        with self.assertRaises(ValueError):
            resolve_screen_group_overscan(CONFIG, [spawns[0],{**spawns[1],'anchor':'caster'}], PLACEMENT)
        with self.assertRaises(ValueError):
            compose([{**spawns[0],'anchor':'caster'}], {'streaks': {'frames': [[]], 'textures': []}}, {'5040290':1.2})
        self.assertEqual({}, resolve_screen_group_overscan(None, [], None))


if __name__ == '__main__':
    unittest.main()
