"""Complete timed imbues retain per-element chances and explicit controls."""
from copy import deepcopy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands
from ability_converter.compiler import TableWriter
from ability_converter.imbues import EVIDENCE

def source(chances=None,turns=3,control=1,**data):
    return SourceRecord('TEST','ability','imbue',{'name':'Elemental blessing',
        'effects_raw':[[2,2,95,(chances or [100]*8)+[turns,control]]],
        'attack_frames':[[24]],'attack_damage':[[100]],**data})

class ImbueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()
    def convert(self,s=None):
        r=self.c.convert(s or source());self.assertTrue(r['validation']['tableCompatible'],r['issues']);return r

    def test_all_eight_imbues_keep_native_ids_lifetime_and_global_filters(self):
        r=self.convert();effects=r['native']['effects']
        self.assertEqual([e['set']['ParamList'][:2] for e in effects],[[v,-1] for v in (1,2,5,6,3,4,7,8)])
        self.assertTrue(all(e['set']['proceedTiming']=='BeginTurn' and e['set']['effectEndActionNum']==3 for e in effects))
        self.assertTrue(all(e['imbue']['nativeEvidence']==EVIDENCE for e in effects))
        self.assertIn('physical and magical',' '.join(r['changes']))
        TableWriter(self.c.native).add(r)

    def test_each_element_preserves_its_own_application_chance(self):
        r=self.convert(source([100,50,0,75,0,0,0,0]))
        self.assertEqual([e['set']['addProbability'] for e in r['native']['effects']],[100,50,75])
        self.assertIn('independently',' '.join(r['changes']))

    def test_turns_cap_at_native_maximum(self):
        r=self.convert(source(turns=99));self.assertTrue(all(e['set']['effectEndActionNum']==10 for e in r['native']['effects']))
        self.assertIn('99 to the native maximum of 10',' '.join(r['changes']))

    def test_nine_slot_formatter_layout_and_zero_elements(self):
        s=source();s.data['effects_raw'][0][3].pop();self.convert(s)
        r=self.convert(source([0]*8));self.assertEqual(r['native']['effects'],[])

    def test_nondefault_control_malformed_chances_duration_and_padding_are_held(self):
        cases=[source(control=0),source(control=2),source(control='1'),source(turns=0),source(turns=1.5),
               source([101]+[0]*7),source([-.1]+[0]*7),source([50.5]+[0]*7),source([True]+[0]*7)]
        extra=source();extra.data['effects_raw'][0][3].append(0);cases.append(extra)
        short=source();short.data['effects_raw'][0][3]=[100]*8;cases.append(short)
        for s in cases:self.assertFalse(self.c.convert(s)['validation']['tableCompatible'],s.data)

    def test_export_rejects_missing_binding_skill_filter_and_clock_changes(self):
        for mutate in (lambda e:e.pop('imbue'),lambda e:e['set']['ParamList'].__setitem__(1,1234),
            lambda e:e['set'].__setitem__('proceedTiming','SkillEnd'),lambda e:e['set'].__setitem__('isUnremovable',True),
            lambda e:e['imbue'].__setitem__('chance',1)):
            r=self.convert();mutate(r['native']['effects'][0]);w=TableWriter(self.c.native)
            with self.assertRaises(ValueError):w.add(r)
            self.assertEqual(w.tables,{})

    def test_command_snapshot_and_support_packing_keep_every_element(self):
        s=source();s.data['effects_raw'].append([2,2,95,[100]*8+[5,1]])
        s.data['attack_frames']=[[24],[24]];s.data['attack_damage']=[[100],[100]]
        p=commands.profile(s);self.assertTrue(p['supported'],p['issues'])
        restored=commands.from_snapshot(p['snapshot']);self.assertTrue(restored['supported'])
        w=TableWriter(self.c.native);w.add(restored['conversion'])
        self.assertEqual(sum(e['set']['EffectType']=='AddElement' for e in w.tables['Skill/DT_SkillEffectData']['add']),16)

    def test_native_template_drift_is_rejected(self):
        native=deepcopy(self.c.native);native.effects[1021]['ParamList'][1]=1
        r=Converter(native=native).convert(source());self.assertFalse(r['validation']['tableCompatible'])

if __name__=='__main__':unittest.main()
