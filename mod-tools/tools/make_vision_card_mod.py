"""Build vision-card items and the Mitra merchant over the installed mod stack."""
from datetime import datetime
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/private')]
import ffrenv
from npc_assets import MAP, SCHEMAS, clone_npc, property_of, set_leaf, dt, dump, run, sha
from verify_mod import equivalent
from vision_cards import catalog, PARAMETERS

STEM = 'zzzzzz_VisionCards_7_P'
SHOP = 771301
TABLES = ('Item/DT_EquipmentItemData', 'Shop/DT_ShopList')


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def build(game):
    cards = catalog()
    assert cards['imported'] == len(cards['cards']), 'Import all card artwork first'
    work = ROOT / 'build/vision-cards' / datetime.now().strftime('package-%Y%m%d-%H%M%S')
    inputs = work / 'inputs'
    inputs.mkdir(parents=True)
    paks = Path(game) / 'FFRS/Content/Paks'
    source_mods = {}
    for path in [*paks.glob('*.utoc'), *paks.glob('*.ucas')]:
        (inputs / path.name).symlink_to(path.resolve())
    for path in (paks / '~mods').iterdir():
        if path.suffix in ('.utoc', '.ucas') and not path.stem.startswith('zzzzzz_VisionCards_'):
            shutil.copy2(path, inputs / path.name)
            source_mods[str(path)] = sha(path)
    legacy, assets = work / 'legacy', work / 'assets'
    for pattern in [MAP, *SCHEMAS, *['Datatable/' + t for t in TABLES]]:
        run([ffrenv.RETOC, 'to-legacy', '--no-shaders', '--filter', pattern, inputs, legacy])
    schemas = [legacy / s for s in SCHEMAS]
    dt('tojson', legacy / MAP, work / 'map-original.json', schemas=schemas)
    original = read(work / 'map-original.json')
    # Mitra's camera looks along X: screen-left is -Y, not deeper into +X.
    edited, npc = clone_npc(original, [134.0, 3734.0, 298.44309316406],
                            donor_name='BP_MapUnit_NPC_C_30', actor_name='BP_MapUnit_NPC_VisionCards',
                            event='DT_Town_010Gra_20_9020_6', unique_id=9470)
    actor = edited['Exports'][npc['actor'] - 1]
    set_leaf(property_of(actor, 'ShopEntry'), ['ShopID'], SHOP)
    dump(work / 'map-edited.json', edited)
    (assets / MAP).parent.mkdir(parents=True)
    dt('fromjson', work / 'map-edited.json', assets / MAP, schemas=schemas)
    dt('tojson', assets / MAP, work / 'map-readback.json', schemas=schemas)
    checked = read(work / 'map-readback.json')
    assert checked['Exports'][npc['actor'] - 1]['ObjectName'] == 'BP_MapUnit_NPC_VisionCards'
    assert len(checked['Exports']) == len(edited['Exports'])
    tables = {}
    for table in TABLES:
        output = work / 'rows' / (table + '.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        dt('rows', legacy / ('FFRS/Content/Datatable/' + table + '.uasset'), output)
        tables[table] = read(output)['rows']
    equipment = tables[TABLES[0]]
    donor = next(k for k, v in equipment.items() if v['ID'] == 12000)
    additions = []
    for card in cards['cards']:
        cid = card['itemId']
        assert all(v['ID'] != cid for v in equipment.values()), f'Item ID collision: {cid}'
        values = {'ID': cid, 'SortId': cid, 'Name': card['name'],
                  'Description': f"Vision Card · Max level {card['maxLevel']}. " + card['description'],
                  'EquipmentType': 'None', 'equipmentDetailType': 'None',
                  'buyingPrice': 1, 'sellingPrice': 0, 'isAvailableSale': False,
                  'params': {f'eUnitParameterType::{PARAMETERS[k]}': v for k, v in card['stats'].items()},
                  'passiveList': [-1, -1, -1, -1]}
        for key in ('nameSg', 'namePl', 'nameDetSg', 'nameDetPl'):
            values[key] = card['name']
        additions.append({'row': 'VisionCard_' + card['id'], 'cloneFrom': donor, 'set': values})
    shop_donor = next(k for k, v in tables[TABLES[1]].items() if v['ShopID'] == 6001)
    edits = [{'asset': 'FFRS/Content/Datatable/' + TABLES[0], 'add': additions},
             {'asset': 'FFRS/Content/Datatable/' + TABLES[1], 'add': [{
                 'row': 'Mitra_VisionCards', 'cloneFrom': shop_donor, 'set': {
                     'ShopID': SHOP, 'ShopName': 'Vision Cards',
                     'ItemList': [{'ItemId': next(c['itemId'] for c in cards['cards'] if c['id']==cid), 'Condition': '', 'MaxOrderNum': -1, 'PriceRatio': 1.0}
                                  for cid in cards['shop']]}}]}]
    dump(work / 'patch.json', {'legacyRoot': str(legacy), 'outRoot': str(assets), 'tables': edits})
    dt('patch', work / 'patch.json')
    for table in TABLES:
        output = work / 'verified' / (table + '.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        dt('rows', assets / ('FFRS/Content/Datatable/' + table + '.uasset'), output)
        actual = read(output)['rows']
        for key, value in tables[table].items():
            assert equivalent(value, actual.get(key)), f'Unrelated row changed: {table}/{key}'
    package = work / 'package'
    package.mkdir()
    run([ffrenv.RETOC, 'to-zen', '--version', 'UE5_6', assets, package / (STEM + '.utoc')])
    result = {'work': str(work), 'package': str(package), 'sourceMods': source_mods,
              'cards': len(cards['cards']), 'shop': cards['shop'], 'npc': npc,
              'files': {p.name: sha(p) for p in package.iterdir()}, 'gameplay': 'NOT_TESTED'}
    dump(work / 'verification.json', result)
    dump(ROOT / 'build/vision-cards/latest-package.json', result)
    print('Built:', package)
    return result


def install(result, game):
    if ffrenv.game_running():
        raise RuntimeError('Close the game before installing vision cards.')
    for name, expected in result['sourceMods'].items():
        if sha(Path(name)) != expected:
            raise RuntimeError('The installed mod stack changed during the build. Rebuild vision cards.')
    destination = Path(game) / 'FFRS/Content/Paks/~mods'
    backup = Path(result['work']) / 'backup'
    backup.mkdir()
    for source in Path(result['package']).iterdir():
        target = destination / source.name
        if target.exists():
            shutil.copy2(target, backup / source.name)
        shutil.copy2(source, target)
        assert sha(target) == sha(source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', default=ffrenv.detect_game())
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    result = build(args.game)
    if args.install:
        install(result, args.game)
