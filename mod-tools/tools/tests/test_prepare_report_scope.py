import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ffbe_effects import prepare_vision as prepare


class PreparationReportScope(unittest.TestCase):
    def test_preparing_one_move_keeps_older_manifest_entries_out_of_current_report(self):
        key='GL_2024/lb/1/level/1'
        native={'kit':{'name':'Fixture','entries':[{'kind':'LB','status':'ready',
            'name':'Current','sourceKey':key}]},'profiles':{key:{'snapshot':{'root':key}}}}
        timeline={'spawns':[],'sounds':[],'issues':[],'targetType':'Single',
                  'visualCoverage':{'complete':True,'omitted':[]}}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); manifest=root/'manifest.json'
            old={'name':'Already prepared','largePriorEvidence':['preserved']*100}
            manifest.write_text(json.dumps({'schema':prepare.presentation.VERSION,
                'form':'1','moves':{'previous':old}}))
            with (patch.object(prepare,'ROOT',root),patch.object(prepare,'WORK',root/'work'),
                  patch.object(prepare,'native_kit',return_value=native),
                  patch.object(prepare,'timeline',return_value=timeline),
                  patch.object(prepare,'AudioLibrary') as audio):
                audio.return_value.selection.return_value={'omitted':{}}
                audit=prepare.prepare(['1'],[key],merge_existing=True,
                                      manifest_out=manifest,make_previews=False)
            self.assertEqual({'previous',key},set(json.loads(manifest.read_bytes())['moves']))
            self.assertEqual(old,json.loads(manifest.read_bytes())['moves']['previous'])
            self.assertEqual([key],list(audit['forms']['1']['moves']))
            self.assertEqual([key],list(json.loads((root/'work/report.json').read_bytes())['forms']['1']['moves']))


if __name__=='__main__':unittest.main()
