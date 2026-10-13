"""Verify converted Fire expiry against the shared native battle-turn clock."""
import argparse
import json
import re
from verify_combat_observation import OUT, read_json, sha
from verify_fire_observation import verify as verify_cast


def verify(directory,build):
    cast=verify_cast(directory,build,expiry=True)
    log=(directory/'collected-ue4ss/UE4SS.log').read_text(encoding='utf8')
    assert 'expiry_read_failed=' not in log
    initial=re.findall(r'expiry_started battle_turn=(\d+) caster_counter=(\d+) enemy_counter=(\d+)',log)
    assert len(initial)==1
    round0,caster0,enemy0=map(int,initial[0])
    turns=[tuple(map(int,row)) for row in re.findall(r'expiry_turn unique=(\d+) battle_turn=(\d+) enemy_counter=(\d+) life=(-?\d+) fire=(\d+)',log)]
    assert turns and {r[0] for r in turns}=={0,1}
    # If Fire acts first, the enemy can start its remaining opportunity in
    # the same shared battle turn. Require every later clock transition and
    # accept that initial-turn observation only at the original lifetime.
    rounds=[r[1] for r in turns]
    assert rounds==sorted(rounds) and all(round0<=r<=round0+5 for r in rounds)
    assert {r for r in rounds if r>round0}==set(range(round0+1,round0+6))
    for unique,round_,enemy_counter,life,resistance in turns:
        elapsed=round_-round0
        assert (life,resistance)==((5-elapsed,1) if elapsed<5 else (-1,0))
    samples=[tuple(map(int,row)) for row in re.findall(r'expiry_sample battle_turn=(\d+) caster_counter=(\d+) enemy_counter=(\d+) caster_hp=(\d+) enemy_hp=(\d+) life=(-?\d+) fire=(\d+)',log)]
    assert samples
    for round_,caster_counter,enemy_counter,caster_hp,enemy_hp,life,resistance in samples:
        elapsed=round_-round0
        assert 0<=elapsed<=5 and caster_hp>0 and enemy_hp==cast['damage']['afterHp']
        assert (life,resistance)==((5-elapsed,1) if elapsed<5 else (-1,0))
    final=re.findall(r'expiry_complete initial_battle_turn=(\d+) final_battle_turn=(\d+) initial_enemy_counter=(\d+) final_enemy_counter=(\d+) caster_hp=(\d+) enemy_hp=(\d+)',log)
    assert len(final)==1
    start,end,first_enemy,last_enemy,hp,enemy_hp=map(int,final[0])
    assert start==round0 and end==round0+5 and first_enemy==enemy0 and hp>0 and enemy_hp==cast['damage']['afterHp']
    defends=[tuple(map(int,row)) for row in re.findall(r'expiry_defend_requested owner=(\d+) turn=(\d+) target=(\d+)',log)]
    assert defends and all(owner==target==0 and turn>caster0 for owner,turn,target in defends)
    assert len({turn for _,turn,_ in defends})==len(defends)==log.count('expiry_defend_returned')
    events=[]
    for match in re.finditer(r'\[FFRAvailability(?:Native|Probe)\] (\{[^\r\n]*\})',log):
        events.append(json.loads(match[1]))
    guards=[e for e in events if e['event']=='native_guard']
    assert all(g['nativeAllowed'] and g['job']==g['rootJob'] and g['targetCount']==g['actionCount']==1 for g in guards)
    player=[g for g in guards if g['actor']==cast['nativeGuard']['actor']]
    assert [g['skillId'] for g in player]==[cast['skillId']]+[400010]*len(defends)
    report={'status':'passed','scope':'converted_fire_five_native_battle_turn_expiry','cast':cast,
        'clock':{'accessor':'CPP_BtlUnitAI.GetTurnNum','nativeFunction':'0x144f52720',
            'field':'CPP_BtlManager + 0x200','initial':start,'final':end,'elapsed':end-start},
        'turnObservations':[dict(zip(('ownerUniqueId','battleTurn','enemyActionCounter','life','fireResistance'),r)) for r in turns],
        'defendCommands':len(defends),'finalCasterHp':hp,'finalEnemyHp':enemy_hp,
        'effectRemoved':True,'fireResistanceRestored':True,
        'productionCommandHold':'released_for_after_damage_resistance' if cast['productionSupportedAtBuild'] else 'retained_at_fixture_build',
        'compatibleRecordsReleased':0,'limitations':['One effect on one living enemy; duration follows native battle turns, not individual owner actions.',
            'Does not validate all categories, recipients, duration modifiers or availability enforcement.']}
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'))
    (OUT/'native-fire-expiry-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
