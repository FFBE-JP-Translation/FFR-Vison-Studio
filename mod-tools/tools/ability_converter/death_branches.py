"""Decode exclusive death-or-damage branches without emitting both branches.

Solaris effect112/effect113 and F_PROCESS_TYPE_MST describe damage only when
death fails. Stock FFR skill 503560 has an InstantDeath bundle before damage,
but its native damage kernel still produces damage with working HP zero.
That composition cannot certify an exclusive branch, including break/rewards.
"""
from copy import deepcopy

EVIDENCE = "build/abilities/native-hit-evidence/death-branch-replay.json"
HOLD = "Death-or-damage needs a per-target failure branch; native InstantDeath followed by damage is not exclusive"


def convert(context):
    from .adapters import integer, number
    p = context.p
    if len(p) not in (3, 4):
        raise ValueError("Death-or-damage requires three parameters and optional defense penetration")
    multiple = number(p[0], "fallback damage coefficient", 0) / 100
    chance = number(p[1], "instant-death chance", 0, 100)
    control = integer(p[2], "death-or-damage source control")
    penetration = number(p[3], "fallback defense penetration", -100, 100) if len(p) == 4 else 0
    physical = context.code == 112
    context.r["semantic"] = {
        "kind": "death_or_damage",
        "evaluation": "per_target",
        "success": {"kind": "instant_death", "chance": chance},
        "failure": {"kind": "damage", "multiple": multiple,
                    "damageType": "Physic" if physical else "Magic",
                    "sourceStat": "ATK" if physical else "MAG",
                    "defenseStat": "DEF" if physical else "SPR",
                    "defenseIgnorePercent": abs(penetration),
                    "sourceDefenseIgnore": penetration},
        # The third parameter is not explained by either source formatter.
        # Preserve it without claiming it is a duration or a second chance.
        "sourceControls": [control],
        "sourceParameters": deepcopy(p),
        "nativeCandidate": {"skill": 503560, "effect": 1219,
                            "phase": "BeforeDamageCalculation", "exclusiveBranch": False},
        "nativeEvidence": EVIDENCE,
        "runtimeValidation": "not_run",
    }
    context.hold(HOLD)
    context.hold("Death-or-damage parameter 3 has no verified source interpretation")
