"""Capture the full traceback for one failed active-move preparation."""
from pathlib import Path
import sys,json,traceback
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/ffbe_effects')]
import prepare_vision as prepare
from ffbe_effects.regional_assets import staged
form,key=sys.argv[1:3]
native=json.loads((ROOT/'data/ffbe/native_kits'/(form+'.json')).read_bytes())
prepare.CACHE=ROOT/'build/ffbe-all-animations/work/decoded'
prepare.WORK=ROOT/'build/animation-recovery/probes'/form/key.replace('/','_')
prepare.WORK.mkdir(parents=True,exist_ok=True)
with staged(prepare,native['profiles'][key]['snapshot'],prepare.WORK/'regional-source'):
    prepare.prepare([form],[key],None,detect_scene=True,merge_existing=True,universal=True,
                    make_previews=False,manifest_out=prepare.WORK/'manifest.json')
