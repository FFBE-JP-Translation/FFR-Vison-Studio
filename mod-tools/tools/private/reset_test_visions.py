"""Stage removal of obsolete test-vision save records, preserving other progress.

Reads the backed-up saves from an existing mod-reset work directory. This tool
does not write to the game or live saves. Only vision ownership, obsolete shop
stock, vision equipment and stale command history can change.
"""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import re

from ffr_party_save import Save, Reader, properties, encode_properties, struct_properties, i32

ROOT = Path(__file__).resolve().parents[2]


def array(prop):
    if prop.type[0] != 'ArrayProperty' or prop.type[1][0][0] != 'StructProperty':
        raise ValueError('Expected a struct array: ' + prop.name)
    reader = Reader(prop.data)
    count = reader.int()
    if not 0 <= count < 10000: raise ValueError('Invalid array count')
    rows = [properties(reader) for _ in range(count)]
    if reader.pos != len(reader.data): raise ValueError('Unrecognized array tail: ' + prop.name)
    return rows


def put(prop, rows):
    prop.data = i32(len(rows)) + b''.join(encode_properties(row) for row in rows)


def clean(raw, key, native_visions, valid_commands, valid_skills):
    save = Save(raw, key)
    before = deepcopy(save)
    obsolete = lambda value: 13000 <= value < 14000 and value not in native_visions
    visions = array(save.props['visionList'])
    removed = [row['ID'].integer() for row in visions if obsolete(row['ID'].integer())]
    retained = [row for row in visions if not obsolete(row['ID'].integer())]
    put(save.props['visionList'], retained)
    shops = array(save.props['shop'])
    shop_removed = [row['ItemId'].integer() for row in shops if obsolete(row['ItemId'].integer())]
    put(save.props['shop'], [row for row in shops if not obsolete(row['ItemId'].integer())])
    members, old_members = save.units(), before.units()
    changed = []
    for row, original in zip(members, old_members):
        uid = row['UnitId'].integer()
        vision = row['equipVisionId'].integer()
        fields = []
        if obsolete(vision):
            row['equipVisionId'].set_integer(-1)
            fields.append('equipVisionId')
        history = struct_properties(row['btlCmdData'])
        actions = array(history['cmdDataList'])
        stale = history['CommandId'].integer() not in valid_commands | valid_skills | {-1}
        stale |= any(a['actionId'].integer() not in valid_skills | {-1} for a in actions)
        if stale:
            attack = row['activeSkillIdList'].integers()[0]
            if attack not in valid_skills: raise ValueError(f'No valid basic attack for unit {uid}')
            history['CommandId'].set_integer(attack)
            for action in actions: action['actionId'].set_integer(attack)
            put(history['cmdDataList'], actions)
            row['btlCmdData'].data = encode_properties(history)
            fields.append('btlCmdData')
        for name in row:
            if name not in fields and row[name].encode() != original[name].encode():
                raise ValueError(f'Unrelated unit field changed: {uid}/{name}')
        if fields: changed.append({'unit':uid,'removedVision':vision if 'equipVisionId' in fields else None,'fields':fields})
    put(save.props['unitParameterList'], members)
    output = save.encode()
    check = Save(output, key)
    allowed = {'visionList','shop','unitParameterList'}
    for name in before.props:
        if name not in allowed and before.props[name].encode() != check.props[name].encode():
            raise ValueError('Unrelated save property changed: ' + name)
    assert check.party() == before.party()
    assert [encode_properties(r) for r in array(check.props['visionList'])] == [encode_properties(r) for r in retained]
    return output, {'removedVisions':removed,'clearedShopEntries':shop_removed,'unitEdits':changed,
                    'party':check.party(),'unrelatedProgressUnchanged':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,required=True)
    args=parser.parse_args()
    work=args.work.resolve()
    if not work.is_relative_to((ROOT/'build/mod-reset').resolve()): raise ValueError('Expected a mod-reset work directory')
    manifest=json.loads((work/'reset.json').read_text(encoding='utf-8'))
    def ids(table):
        return {v['ID'] for v in json.loads((ROOT/'extracted/rows'/f'{table}.json').read_text(encoding='utf-8'))['rows'].values()}
    visions=ids('Item/Vision/DT_VisionItemData')
    commands=ids('Skill/DT_CommandSkillData')
    # The staged party builder has validated these private moves with the base tables.
    party=json.loads((ROOT/'build/party-members/latest.json').read_text(encoding='utf-8'))
    skills=ids('Skill/DT_SkillData') | {s for u in party['units'] for s in u['skills']}
    key=re.search(r'^SaveDataEncryptionKey=(.+)$',(ROOT/'extracted/pak/FFRS/Config/DefaultSaveGameUtility.ini').read_text(),re.M).group(1).strip().encode()
    reports=[]
    for info in manifest['saves']:
        path=Path(info['path'])
        if not path.name.startswith('GameSaveData'): continue
        source=work/'backup/saves'/path.parent.name/path.name
        raw=source.read_bytes()
        assert hashlib.sha256(raw).hexdigest()==info['sha256']
        output,report=clean(raw,key,visions,commands,skills)
        again,_=clean(output,key,visions,commands,skills)
        assert again==output, 'Cleanup is not idempotent'
        target=work/'clean-saves'/path.parent.name/path.name
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(output)
        reports.append({'path':str(path),'staged':str(target),'beforeSha256':info['sha256'],
                        'afterSha256':hashlib.sha256(output).hexdigest(),**report})
    (work/'save-cleanup.json').write_text(json.dumps(reports,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([{'save':Path(r['path']).name,'removedVisions':len(r['removedVisions']),
                      'clearedShopEntries':len(r['clearedShopEntries']),'unequipped':sum(e['removedVision'] is not None for e in r['unitEdits']),
                      'progressUnchanged':r['unrelatedProgressUnchanged']} for r in reports]))


if __name__=='__main__': main()
