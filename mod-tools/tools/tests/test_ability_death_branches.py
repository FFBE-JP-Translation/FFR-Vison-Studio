"""A death attempt and unconditional damage must not masquerade as fallback."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from ability_converter import Converter, SourceRecord
from ability_converter.death_branches import HOLD


class DeathBranchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.converter = Converter()

    def convert(self, code=112, params=None, kind='ability'):
        source = SourceRecord('TEST', kind, '123', {'name':'Death or damage',
            'effects_raw':[[1,1,code,params if params is not None else [1400,70,100,0]]],
            'attack_frames':[[12]],'attack_damage':[[100]],'move_type':0})
        return self.converter.convert(source)

    def test_physical_branches_and_control_are_retained_without_emission(self):
        r=self.convert(params=[3500,95,155,-50]); c=r['components'][0]; s=c['semantic']
        self.assertFalse(r['validation']['tableCompatible']); self.assertIn(HOLD,c['issues'])
        self.assertEqual((c['effects'],c['actions'],c['dependencies']),([],[],[]))
        self.assertEqual(s['success'],{'kind':'instant_death','chance':95})
        self.assertEqual((s['failure']['multiple'],s['failure']['damageType'],s['failure']['sourceStat']), (35,'Physic','ATK'))
        self.assertEqual((s['failure']['defenseIgnorePercent'],s['failure']['sourceDefenseIgnore']), (50,-50))
        self.assertEqual(s['sourceControls'],[155]);self.assertEqual(s['evaluation'],'per_target')
        self.assertFalse(s['nativeCandidate']['exclusiveBranch'])

    def test_magic_retains_signed_source_and_spr_basis(self):
        s=self.convert(113,[4400,30,348,50])['components'][0]['semantic']
        self.assertEqual((s['failure']['multiple'],s['failure']['damageType'],s['failure']['sourceStat'],s['failure']['defenseStat']), (44,'Magic','MAG','SPR'))
        self.assertEqual(s['failure']['sourceDefenseIgnore'],50)

    def test_optional_penetration_defaults_without_altering_raw_layout(self):
        r=self.convert(params=[500,60,100]);s=r['components'][0]['semantic']
        self.assertEqual(s['sourceParameters'],[500,60,100])
        self.assertEqual(s['failure']['defenseIgnorePercent'],0)

    def test_zero_and_guaranteed_chances_do_not_bypass_source_control_or_immunity(self):
        for chance in (0,100):
            with self.subTest(chance=chance):
                r=self.convert(params=[500,chance,0,0])
                self.assertFalse(r['validation']['tableCompatible'])
                self.assertEqual(r['components'][0]['effects'],[])

    def test_bad_layout_and_nonfinite_or_out_of_range_values_stay_held(self):
        for p in ([500], [500,50,100,0,7], [-1,50,100,0], [500,101,100,0],
                  [500,float('nan'),100,0], [500,50,1.5,0], [500,50,100,101]):
            with self.subTest(params=p):
                r=self.convert(params=p)
                self.assertFalse(r['validation']['tableCompatible'])
                self.assertTrue(r['components'][0]['issues'])
                self.assertEqual(r['components'][0]['actions'],[])

    def test_enemy_and_lb_use_the_same_exclusive_contract(self):
        for kind in ('enemy','lb'):
            r=self.convert(kind=kind)
            self.assertEqual(r['components'][0]['semantic']['kind'],'death_or_damage')
            self.assertFalse(r['validation']['tableCompatible'])

    def test_doom_remains_a_separate_scheduled_mechanic(self):
        r=self.convert(1001,[3,0,100])
        self.assertEqual(r['components'][0]['semantic']['kind'],'death_branch_or_doom')
        self.assertFalse(r['validation']['tableCompatible'])


if __name__ == '__main__':
    unittest.main()
