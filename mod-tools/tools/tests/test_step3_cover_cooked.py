"""Read real cooked cover projection and retain legacy projection compatibility."""
from pathlib import Path
import shutil, sys, tempfile, unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/tests')]
from tools.tests import test_ffbe_native_aura as aura
from tools.tests import test_ffbe_native_stage_camera as stage
import make_vision_mod as generator
import ffbe_resonance

class CoverCooked(unittest.TestCase):
    command=classmethod(aura.NativeAuraCooked.command.__func__)
    dump=classmethod(aura.NativeAuraCooked.dump.__func__)
    patch=classmethod(aura.NativeAuraCooked.patch.__func__)
    walk=staticmethod(stage.NativeStageCameraCooked.walk)

    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='step3-cover-', dir=ROOT/'build')
        cls.addClassCleanup(cls.temp.cleanup); cls.work=Path(cls.temp.name)
        cls.asset=cls.work/'shell.uasset'; cls.usmap=cls.work/'Mappings.usmap'
        shutil.copy2(generator.USMAP, cls.usmap)

    def test_cover_and_legacy_round_trip_and_uniform_scale(self):
        source=Path(generator.LEGACY)/(ffbe_resonance.SHELL+'.uasset')
        for cover in (None,True):
            for suffix in ('.uasset','.uexp','.ubulk'):
                if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix),self.asset.with_suffix(suffix))
            identifier=next(k.split(':')[0] for k,v in self.dump('seqdump').items()
                            if isinstance(v,dict) and v.get('$struct')=='BTL_SEQUENCE_PARAMETER')
            event={'EventType':'NativeScreenPlane','NativeScreenPlane_Id':'FFBE_test',
                   'NativeScreenPlane_SourceWidth':320., 'NativeScreenPlane_SourceHeight':320.,
                   'NativeScreenPlane_RuntimeScale':.8, 'NativeScreenPlane_OverscanX':1.06,
                   'NativeScreenPlane_OverscanY':1.06,'NativeScreenPlane_FrontDepth':1000.,
                   'NativeScreenPlane_RearMargin':300., 'NativeScreenPlane_IsRear':False}
            if cover is not None:
                event['NativeScreenPlane_Cover']=cover
                event['NativeScreenPlane_VisionUnitId']=13503
                event['NativeScreenPlane_ViewportRise']=.12
            result=self.patch([{'asset':'shell','export':identifier,'set':event}])
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)
            readback=self.dump('seqdump')
            self.assertEqual(event,next(v for k,v in readback.items() if k.startswith(identifier+':')))
            doc=self.dump('tojson'); fn=doc['Exports'][int(identifier)-1]
            name=lambda call: doc['Imports'][-call['StackNode']-1]['ObjectName']
            setter=next(c for c in self.walk(fn['ScriptBytecode']) if 'StackNode' in c and name(c)=='SetRelativeScale3D')
            axes=setter['Parameters'][0]['Parameters'][1:]
            if cover:
                self.assertTrue(any('StackNode' in c and name(c)=='SetTranslucentSortPriority' for c in self.walk(fn['ScriptBytecode'])))
                self.assertEqual(axes[0],axes[1])
                self.assertEqual('FMax',name(axes[0]))
            else:
                self.assertNotEqual(axes[0],axes[1])

if __name__ == '__main__': unittest.main()
