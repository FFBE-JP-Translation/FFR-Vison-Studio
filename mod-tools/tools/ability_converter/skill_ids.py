"""Numeric categories used by native CPP_BFL_Skill.GetSkillCategory.

The demo's native body at RVA 0x513fbd0 classifies IDs before looking up rows:
1..999 command, 1000..99999 passive, 100000..999999 active, >=1000000 master.
Effects have their own table and do not pass through this classification.
"""

ID_RANGES = {"skills": (100_000, 1_000_000), "passives": (1_000, 100_000),
             "effects": (1, 2_147_483_647)}
ID_STARTS = {"skills": 100_000, "passives": 1_000, "effects": 100_000_000}


def vision_passive_base(vision_id):
    """One hundred stable passive slots per imported vision, 13100..13999."""
    if type(vision_id) is not int or not 13100 <= vision_id <= 13999:
        raise ValueError('Converted passive allocation requires vision ID 13100..13999')
    return 10000 + (vision_id-13100)*100


def validate_id(kind, value):
    start, stop = ID_RANGES[kind]
    if type(value) is not int or not start <= value < stop:
        raise ValueError(f"Invalid {kind} ID {value!r}: native range is {start}..{stop-1}. "
                         "An incompatible persisted ledger must be archived and rebuilt; IDs are never silently remapped.")
