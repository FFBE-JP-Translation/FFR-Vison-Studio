"""Lossless edits to the local demo's party records (SVHD + AES-ECB GVAS).

The caller handles backups and installation. This module only returns bytes.
Unknown top-level payloads are retained verbatim; no inventory or story fields
are decoded or rewritten.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import struct

from Crypto.Cipher import AES


def i32(value):
    return struct.pack("<i", value)


def fstring(value):
    encoded = value.encode("utf-8") + b"\0"
    return i32(len(encoded)) + encoded


class Reader:
    def __init__(self, data, offset=0):
        self.data, self.pos = data, offset

    def read(self, size):
        if size < 0 or self.pos + size > len(self.data):
            raise ValueError("Truncated save data")
        value = self.data[self.pos:self.pos + size]
        self.pos += size
        return value

    def int(self):
        return struct.unpack("<i", self.read(4))[0]

    def string(self):
        size = self.int()
        if abs(size) > 1_000_000:
            raise ValueError("Invalid save string length")
        if size == 0:
            return ""
        return (self.read(size)[:-1].decode("utf-8") if size > 0 else
                self.read(-size * 2)[:-2].decode("utf-16-le"))

    def type_name(self):
        name, count = self.string(), self.int()
        if not 0 <= count <= 16:
            raise ValueError("Unexpected property type parameters")
        return name, [self.type_name() for _ in range(count)]


@dataclass
class Property:
    name: str
    type: tuple
    prefix: bytes
    flags: int
    data: bytes

    def encode(self):
        return self.prefix + i32(len(self.data)) + bytes([self.flags]) + self.data

    def integer(self):
        if self.type[0] != "IntProperty" or len(self.data) != 4:
            raise ValueError(f"Expected integer: {self.name}")
        return struct.unpack("<i", self.data)[0]

    def set_integer(self, value):
        self.integer()
        self.data = i32(value)

    def integers(self):
        if self.type != ("ArrayProperty", [("IntProperty", [])]):
            raise ValueError(f"Expected integer array: {self.name}")
        reader = Reader(self.data)
        count = reader.int()
        if count < 0 or len(self.data) != 4 + 4 * count:
            raise ValueError(f"Malformed integer array: {self.name}")
        return [reader.int() for _ in range(count)]

    def set_integers(self, values):
        self.integers()
        self.data = i32(len(values)) + b"".join(i32(value) for value in values)

    def set_bool(self, value):
        if self.type[0] != "BoolProperty" or self.data:
            raise ValueError(f"Expected inline boolean: {self.name}")
        self.flags = 0x10 if value else 0


def properties(reader):
    result = {}
    while True:
        start = reader.pos
        name = reader.string()
        if name == "None":
            return result
        type_name = reader.type_name()
        prefix = reader.data[start:reader.pos]
        size, flags = reader.int(), reader.read(1)[0]
        if flags not in (0, 0x10):
            raise ValueError(f"Unsupported property flags {flags:#x} on {name}")
        if name in result:
            raise ValueError(f"Duplicate property: {name}")
        result[name] = Property(name, type_name, prefix, flags, reader.read(size))


def encode_properties(values):
    return b"".join(prop.encode() for prop in values.values()) + fstring("None")


def struct_properties(prop):
    reader = Reader(prop.data)
    values = properties(reader)
    if reader.pos != len(prop.data):
        raise ValueError(f"Unexpected struct tail: {prop.name}")
    return values


class Save:
    def __init__(self, encrypted, key):
        if encrypted[:4] != b"SVHD" or len(encrypted) < 48 or len(encrypted) % 16:
            raise ValueError("Unsupported save envelope")
        if hashlib.sha1(encrypted[32:]).digest() != encrypted[8:28]:
            raise ValueError("Save checksum mismatch")
        self.header, self.key = encrypted[:32], key
        plain = AES.new(key, AES.MODE_ECB).decrypt(encrypted[32:])
        reader = Reader(plain)
        if reader.read(4) != b"GVAS" or reader.int() != 3:
            raise ValueError("Unsupported GVAS version or encryption key")
        reader.read(8 + 6 + 4)  # UE4/UE5 package versions, engine version, changelist
        reader.string()  # engine branch
        if reader.int() != 3:
            raise ValueError("Unsupported custom version format")
        count = reader.int()
        if not 0 <= count <= 1000:
            raise ValueError("Invalid custom version count")
        reader.read(20 * count)
        if reader.string() != "/Script/mucha.CPP_MuchaGameSaveData":
            raise ValueError("This is not a game-progress save")
        if reader.read(1) != b"\0":
            raise ValueError("Unsupported object serialization extensions")
        self.prefix = plain[:reader.pos]
        self.props = properties(reader)
        self.tail = plain[reader.pos:]
        if self.tail.strip(b"\0"):
            raise ValueError("Unexpected data after the GVAS object")
        if self.encode() != encrypted:
            raise ValueError("Save did not round-trip byte-for-byte")

    def encode(self):
        plain = self.prefix + encode_properties(self.props) + self.tail
        plain += b"\0" * (-len(plain) % 16)
        cipher = AES.new(self.key, AES.MODE_ECB).encrypt(plain)
        return self.header[:8] + hashlib.sha1(cipher).digest() + self.header[28:] + cipher

    def units(self):
        prop = self.props["unitParameterList"]
        if prop.type[0] != "ArrayProperty" or prop.type[1][0][0] != "StructProperty":
            raise ValueError("Unexpected unit array type")
        reader = Reader(prop.data)
        count = reader.int()
        if count != 8:
            raise ValueError(f"Expected the demo's eight party slots; found {count}")
        units = [properties(reader) for _ in range(count)]
        if reader.pos != len(prop.data):
            raise ValueError("Unexpected unit array tail")
        return units

    def party(self):
        return struct_properties(self.props["Party"])["partyList"].integers()


def add_test_party(encrypted, key, units):
    """Replace the two unused demo slots, keeping Rain and all other state intact.

    units: [{id, skills, attack}]. Existing test members retain their current
    equipment and stats on repeat installation; unrecruited slots start from Rain.
    """
    save = Save(encrypted, key)
    original = deepcopy(save)
    members = save.units()
    by_id = {row["UnitId"].integer(): row for row in members}
    rain = by_id[1001]
    party = struct_properties(save.props["Party"])
    party_ids = party["partyList"].integers()
    if any(uid not in (1001, 1002, 1007, 1008) for uid in party_ids):
        raise ValueError("This helper is for the Rain/Lasswell demo test party")
    before = list(party_ids)
    changed = []
    for unit in units:
        uid = unit["id"]
        if uid not in (1007, 1008):
            raise ValueError("Only the Jake/Sakura test slots can be changed")
        old = by_id[uid]
        already_joined = Reader(old["JoinStatus"].data).string() == "eUnitJoinStatus::Join"
        if already_joined and unit["attack"] not in old["activeSkillIdList"].integers():
            raise ValueError(f"Slot {uid} is already recruited outside the private party addon")
        row = old if already_joined else deepcopy(rain)
        if not already_joined:
            row["UnitId"].set_integer(uid)
            row["equipVisionId"].set_integer(-1)
            row["EquipWeaponId"].set_integer(10100)  # Rain's native starting greatsword
            row["EquipArmorId"].set_integer(-1)
            row["EquipAccessoryIdList"].set_integers([-1] * len(rain["EquipAccessoryIdList"].integers()))
            row["equipSkillList"].set_integers([-1] * len(rain["equipSkillList"].integers()))
            row["passiveSkillIdList"].set_integers([])
            row["commandSkillIdList"].set_integers([])
            row["defeatUnitNum"].set_integer(0)
            row["btlCmdData"] = deepcopy(old["btlCmdData"])
            for field, option in (("HitPoint", "startingHp"), ("MagicPoint", "startingMp")):
                if option in unit:
                    row[field].set_integer(unit[option])
            history = struct_properties(row["btlCmdData"])
            history["CommandId"].set_integer(unit["attack"])
            commands = Reader(history["cmdDataList"].data)
            count = commands.int()
            entries = [properties(commands) for _ in range(count)]
            if commands.pos != len(commands.data):
                raise ValueError("Unexpected command history tail")
            for entry in entries:
                entry["actionId"].set_integer(unit["attack"])
            history["cmdDataList"].data = i32(count) + b"".join(encode_properties(entry) for entry in entries)
            row["btlCmdData"].data = encode_properties(history)
        row["JoinStatus"].data = fstring("eUnitJoinStatus::Join")
        row["IsUsable"].set_bool(True)
        learned = row["activeSkillIdList"].integers() if already_joined else []
        row["activeSkillIdList"].set_integers(list(dict.fromkeys(learned + unit["skills"])))
        members[next(i for i, item in enumerate(members) if item["UnitId"].integer() == uid)] = row
        if uid not in party_ids:
            party_ids.append(uid)
        changed.append({"unitId": uid, "experience": row["Experience"].integer(),
                        "visionId": row["equipVisionId"].integer(), "skills": row["activeSkillIdList"].integers()})
    if len(party_ids) > 4:
        raise ValueError("No empty battle-party slots")
    party["partyList"].set_integers(party_ids)
    save.props["Party"].data = encode_properties(party)
    save.props["unitParameterList"].data = i32(len(members)) + b"".join(encode_properties(row) for row in members)
    output = save.encode()
    check = Save(output, key)
    for name, prop in original.props.items():
        if name not in ("Party", "unitParameterList") and check.props[name].encode() != prop.encode():
            raise ValueError(f"Unrelated save data changed: {name}")
    check_units = {row["UnitId"].integer(): row for row in check.units()}
    for uid, row in by_id.items():
        if uid not in (1007, 1008) and encode_properties(check_units[uid]) != encode_properties(row):
            raise ValueError(f"Unrelated unit changed: {uid}")
    if check.party() != party_ids:
        raise ValueError("Party readback mismatch")
    return output, {"beforeParty": before, "afterParty": party_ids, "units": changed,
                    "unrelatedSaveDataUnchanged": True}
