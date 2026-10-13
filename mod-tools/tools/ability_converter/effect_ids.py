"""Preserve the ordinary 100-row owner range; spill large private graphs safely.

Overflow IDs occupy a separate high positive int32 bank. Hashing the owner
and row key makes allocation reproducible; collisions within this package
or with native rows are probed explicitly. As with ordinary skill IDs,
independently built mods must still be checked together for ID conflicts.
"""
import hashlib

from .compiler import TableWriter

START = 2_000_000_000
STOP = 2_100_000_000
SKILL_START = 600_000
SKILL_STOP = 900_000


class OwnedEffectWriter(TableWriter):
    def __init__(self,native,ledger,owner,occupied,occupied_skills=()):
        super().__init__(native,ledger)
        self.skill_occupied=set(occupied_skills)
        self.effect_owner=owner
        self.effect_limit=owner*100+100
        self.effect_occupied=set(occupied)
        self.overflow_ids=set()

    def allocate(self,kind,key):
        if kind == 'skills' and key not in self.ledger[kind]:
            # Private applications are still ActiveSkill rows. owner*100 puts
            # them in MasterSkill and breaks native category-based consumers.
            payload=f'ffr-private-skill-v1:{self.effect_owner}:{key}'.encode()
            value=SKILL_START+int.from_bytes(hashlib.sha256(payload).digest()[:8],'big')%(SKILL_STOP-SKILL_START)
            initial=value
            while value in self.used[kind]:
                value=SKILL_START+(value+1-SKILL_START)%(SKILL_STOP-SKILL_START)
                if value==initial:
                    raise ValueError('Private active skill ID range exhausted')
            if value in self.skill_occupied:
                raise ValueError(f'Duplicate converted application ID {value}')
            self.ledger[kind][key]=value
            self.used[kind].add(value)
            return value
        if (kind!='effects' or key in self.ledger[kind]
                or self.next_ids[kind]<self.effect_limit):
            return super().allocate(kind,key)
        payload=f'ffr-private-effect-v1:{self.effect_owner}:{key}'.encode()
        value=START+int.from_bytes(hashlib.sha256(payload).digest()[:8],'big')%(STOP-START)
        initial=value
        while value in self.used[kind] or value in self.effect_occupied:
            value=START+(value+1-START)%(STOP-START)
            if value==initial:
                raise ValueError('Private effect overflow bank exhausted')
        self.ledger[kind][key]=value
        self.used[kind].add(value)
        self.overflow_ids.add(value)
        return value
