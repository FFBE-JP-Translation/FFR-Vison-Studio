"""Stop remains distinct from Paralysis through conversion and command export."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,SourceRecord,commands
from ability_converter.compiler import TableWriter
from ability_converter.stop import PARAMS


def source(chance=80,turns=3,padding=False,shape=2,side=1,**data):
    return SourceRecord('TEST','magic','88',{'name':'Stop',
        'effects_raw':[[shape,side,88,[chance,turns]+([0]*8 if padding else [])]],
        'attack_frames':[[24]],'attack_damage':[[100]],'mp_cost':12,**data})


class StopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()

    def convert(self,**kw):
        r=self.c.convert(source(**kw));self.assertTrue(r['validation']['tableCompatible'],r['issues'])
        self.assertEqual(r['status'],'adapted');return r

    def test_separate_stop_identity_retains_incapacitation_and_chance(self):
        for chance in (0,1,33,80,100):
            r=self.convert(chance=chance);effect=r['native']['effects'][0]
            self.assertEqual(effect['set']['statusCondition'],'Stop')
            self.assertEqual(effect['set']['ParamList'],PARAMS)
            self.assertEqual(effect['set']['addProbability'],chance)
            self.assertEqual(effect['set']['activationProbability'],100)
            self.assertEqual(effect['set']['applyTiming'],'ActionBegin')
            self.assertFalse(effect['set']['isUnremovable'])

    def test_duration_uses_turn_clock_and_explicit_native_cap(self):
        for turns in (1,3,5,10,999):
            r=self.convert(turns=turns);effect=r['native']['effects'][0]
            self.assertEqual((effect['set']['proceedTiming'],effect['set']['effectEndActionNum']),('BeginTurn',min(turns,10)))
            self.assertEqual(r['components'][0]['semantic']['sourceTurns'],turns)
            self.assertEqual(any('capped' in c for c in r['changes']),turns>10)

    def test_zero_padding_is_retained_and_nonzero_padding_holds(self):
        self.assertEqual(self.convert()['native'],self.convert(padding=True)['native'])
        for value in (1,-1,True,'0',.5):
            record=source(padding=True);record.data['effects_raw'][0][3][-1]=value
            r=self.c.convert(record);self.assertFalse(r['validation']['tableCompatible'])
            self.assertFalse(r['components'][0]['effects'])

    def test_malformed_source_is_not_silently_truncated(self):
        for params in ([],[80],[80,3,0],[80,3]+[0]*9,[101,3],[-1,3],[True,3],['80',3],[33.5,3],[80,0],[80,-1],[80,2.5]):
            record=source();record.data['effects_raw'][0][3]=params
            self.assertFalse(self.c.convert(record)['validation']['tableCompatible'],params)

    def test_cures_and_resistance_reference_stop_instead_of_paralysis(self):
        record=source();record.data['effects_raw'] += [[2,2,111,[0,0,0,0,1,0]], [2,2,89,[0,0,0,0,100,0,4]]]
        # A common selected side keeps this fixture within one support action.
        for raw in record.data['effects_raw']:raw[1]=2
        r=self.c.convert(record);self.assertTrue(r['validation']['tableCompatible'],r['issues'])
        effects=r['native']['effects']
        self.assertEqual(effects[1]['set']['ParamList'][3],9)
        self.assertEqual(effects[2]['set']['ParamList'][:2],[9,100])

    def test_command_snapshot_retains_stop_duration_and_recipient(self):
        p=commands.profile(source(shape=1));self.assertTrue(p['supported'],p['issues'])
        restored=commands.from_snapshot(p['snapshot'])
        self.assertIn('Stop',restored['description']);self.assertIn('80%',restored['description'])
        self.assertEqual(restored['timeline']['hitFrames'],[24])
        w=TableWriter(self.c.native);w.add(restored['conversion'])
        row=w.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertEqual((row['TargetType'],row['defaultTargetRelation']),('Single','Enemies'))

    def test_missing_or_tampered_contract_is_rejected_before_allocation(self):
        for mutate in (lambda e:e.pop('stop'),lambda e:e['stop'].__setitem__('chance',50),
                       lambda e:e['set'].__setitem__('statusCondition','Paralyzation'),
                       lambda e:e['set']['ParamList'].__setitem__(0,0),
                       lambda e:e['set'].__setitem__('isUnremovable',True),
                       lambda e:e['set'].__setitem__('proceedTiming','ActionEnd')):
            r=self.convert();mutate(r['native']['effects'][0]);w=TableWriter(self.c.native)
            with self.assertRaises(ValueError):w.add(r)
            self.assertEqual(w.tables,{});self.assertTrue(all(not ids for ids in w.ledger.values()))

    def test_native_metadata_or_template_drift_is_rejected(self):
        for name in ('Stop','Paralyzation'):
            native=deepcopy(self.c.native)
            next(s for s in native.inventory['statuses'] if s['statusCondition']==name)['isActionDisabled']=False
            r=Converter(native=native).convert(source())
            self.assertFalse(r['validation']['tableCompatible']);self.assertIn('policy changed',' '.join(r['issues']))
        native=deepcopy(self.c.native);native.effects[1033]['ParamList'][5]=0
        self.assertFalse(Converter(native=native).convert(source())['validation']['tableCompatible'])

    def test_damage_and_stop_keep_the_native_support_phase(self):
        record=source();record.data['effects_raw'].insert(0,[2,1,1,[0,0,0,0,0,0,500]])
        p=commands.profile(record);self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(p['conversion']['native']['set']['DamageType'],'Physic')
        self.assertEqual(p['conversion']['native']['effects'][0]['activeTiming'],'AfterDamageCalculation')


if __name__=='__main__':unittest.main()
