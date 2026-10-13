"""Large private graphs retain ordinary IDs and reject or avoid collisions."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from ability_converter import Converter,commands
from ability_converter.effect_ids import OwnedEffectWriter,START,STOP
from test_ability_random import source


class EffectIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.c=Converter()

    def writer(self,occupied=(),owner=1900010):
        writer=OwnedEffectWriter(self.c.native,{'skills':{},'effects':{},'passives':{}},owner,occupied)
        writer.next_ids['effects']=owner*100
        return writer

    def test_first_hundred_ids_remain_unchanged_then_use_overflow(self):
        writer=self.writer()
        ids=[writer.allocate('effects',str(i)) for i in range(700)]
        self.assertEqual(ids[:100],list(range(190001000,190001100)))
        self.assertTrue(all(START<=v<STOP for v in ids[100:]))
        self.assertEqual(len(set(ids)),700)
        self.assertEqual(writer.next_ids['effects'],190001100)
        self.assertEqual([writer.allocate('effects',str(i)) for i in range(700)],ids)

    def test_overflow_is_reproducible_and_owner_specific(self):
        writers=[self.writer(),self.writer(),self.writer(owner=1900011)]
        for writer in writers:writer.next_ids['effects']=writer.effect_limit
        values=[[w.allocate('effects',str(i)) for i in range(200)] for w in writers]
        self.assertEqual(values[0],values[1]);self.assertFalse(set(values[0]) & set(values[2]))

    def test_overflow_skips_existing_and_native_ids(self):
        seed=self.writer();seed.next_ids['effects']=seed.effect_limit
        proposed=seed.allocate('effects','collision')
        writer=self.writer([proposed,proposed+1]);writer.next_ids['effects']=writer.effect_limit
        writer.used['effects'].add(proposed+2)
        self.assertEqual(writer.allocate('effects','collision'),proposed+3)

    def test_large_neighboring_commands_materialize_complete_private_graphs(self):
        tables={}
        def tbl(name):return tables.setdefault(name,{'add':[],'set':[]})
        def row_by(*args):return {}
        profile=commands.profile(source([40]*8,3,code=34))
        self.assertTrue(profile['supported'],profile['issues'])
        first=commands.materialize(profile,890010,'One',tbl,row_by)
        rows=tables['Skill/DT_SkillEffectData']['add'];old={r['set']['ID'] for r in rows}
        self.assertGreater(len(old),100)
        second=commands.materialize(profile,890011,'Two',tbl,row_by)
        ids=[r['set']['ID'] for r in rows]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertNotEqual(first['effectBundleList'][0]['effectId'],second['effectBundleList'][0]['effectId'])
        all_ids=set(ids)
        for row in rows:
            effect=row['set']
            if effect['EffectType'] in ('AddEffect','AddRandEffect'):
                self.assertTrue(all(v in all_ids for v in effect['ParamList'][1:6] if v!=-1))
        before=deepcopy(tables)
        with self.assertRaisesRegex(ValueError,'Duplicate converted effect'):
            commands.materialize(profile,890010,'Duplicate',tbl,row_by)
        self.assertEqual(tables,before)


if __name__=='__main__':unittest.main()
