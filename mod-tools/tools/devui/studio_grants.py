"""Draft-only editing of a vision's grants; stock catalog rows stay reusable."""
import ffr_catalog
import reviewed_kits
import vision_import as kits
from ability_converter.skill_ids import vision_passive_base


def selection(unit, ref):
    key = ref.get('sourceKey')
    if key:
        entry = next((e for e in unit.get('ffbeLibrary', []) if e['sourceKey'] == key), None)
        if entry is None: raise ValueError('That native ability is not in this vision')
        found = kits.imported(unit, key)
        return entry, found
    kind, sid = ref['kind'], str(ref['id'])
    group = {'ActiveSkill': 'skills', 'PassiveSkill': 'convertedPassives'}.get(kind)
    if group is None: raise ValueError('Choose an ability or passive')
    recipe = unit.get(group, {}).get(sid)
    if recipe: return recipe, (group, sid)
    rows = ffr_catalog.load()['passives' if kind == 'PassiveSkill' else 'skills']
    row = next((r for r in rows if r['id'] == int(sid)), None)
    if row is None: raise ValueError('The selected ability is no longer available')
    return row, None


def information(unit, ref):
    entry, found = selection(unit, ref)
    key = ref.get('sourceKey') or entry.get('ffbe', {}).get('source')
    recipe = {}
    if found: recipe = unit[found[0]] if found[0] == 'lb_custom' else unit[found[0]][found[1]]
    result = {'entry': entry, 'recipe': recipe}
    if key: result['conversion'] = reviewed_kits.profile(key, unit['ffbe']['id'])
    else:
        if recipe:
            stock = ffr_catalog.load()['passives' if found[0] == 'convertedPassives' else 'skills']
            result['nativeTemplate'] = next((e for e in stock if e['id'] == recipe['from']), {})
        ids = result.get('nativeTemplate', entry).get('effects', [])
        result['effects'] = [e for e in ffr_catalog.load()['effects'] if e['id'] in ids]
    return result


def edit(unit, ref, edits):
    if not isinstance(edits.get('name'), str) or not edits['name'].strip(): raise ValueError('Enter a name')
    if not isinstance(edits.get('description'), str): raise ValueError('Enter a description')
    if type(edits.get('cost')) is not int or not 0 <= edits['cost'] <= 9999: raise ValueError('Cost must be a whole number from 0 to 9999')
    edits = {**edits, 'name': edits['name'].strip()}
    icons = {i['tag'] for i in ffr_catalog.load()['icons']}
    if edits.get('icon') and edits['icon'] not in icons: raise ValueError('Choose an available game icon')
    entry, found = selection(unit, ref)
    key = ref.get('sourceKey') or entry.get('ffbe', {}).get('source')
    passive = entry.get('kind') == 'PASSIVE' or ref.get('kind') == 'PassiveSkill' or found and found[0] == 'convertedPassives'
    if key:
        unit.setdefault('nativeEdits', {})[key] = edits
        if not found: return unit
    if found:
        recipe = unit[found[0]] if found[0] == 'lb_custom' else unit[found[0]][found[1]]
    else:
        group = 'convertedPassives' if passive else 'skills'
        base = vision_passive_base(unit['id']) if passive else 445000 + (unit['id']-13100)*100
        slots = unit.setdefault(group, {})
        sid = next((i for i in range(base, base+100, 1 if passive else 10) if str(i) not in slots), None)
        if sid is None: raise ValueError('No custom slots remain for this edit. Remove a custom move first.')
        recipe = {'from': entry['id'], 'mechanics': 'native', 'jp': f"{unit['jp']}_Edited_{sid}",
                  'en': entry['name'], 'desc': entry.get('desc', ''), 'set': {}}
        slots[str(sid)] = recipe
        for field in ('awakening', 'synchro'):
            for tier in unit.get(field, []):
                for grant in tier:
                    if grant[:2] == [ref['kind'], entry['id']]: grant[1] = sid
    kits.apply_edits(recipe, edits, passive)
    return unit


def action(unit, body):
    operation = body['action']
    if operation == 'import': return kits.import_native(unit, body['group'])
    if operation == 'edit': return edit(unit, body['ref'], body['edits'])
    if operation == 'info': return information(unit, body['ref'])
    if operation == 'assign':
        key = body['sourceKey']
        kits.equip(unit, key, target_tier=body['tier'])
        found = kits.imported(unit, key)
        if found and found[0] != 'lb_custom' and body.get('index') is not None:
            kind = 'PassiveSkill' if found[0] == 'convertedPassives' else 'ActiveSkill'
            tier = unit['awakening'][body['tier']]
            grant = [kind, int(found[1])]
            if grant in tier:
                tier.remove(grant)
                tier.insert(max(0, min(int(body['index']), len(tier))), grant)
        selected = unit.setdefault('nativeImports', [])
        if key not in selected: selected.append(key)
        return unit
    if operation == 'remove':
        tier, index = body['tier'], body['index']
        grant = unit['awakening'][tier][index]
        group = {'ActiveSkill': 'skills', 'PassiveSkill': 'convertedPassives'}.get(grant[0])
        recipe = unit.get(group, {}).get(str(grant[1])) if group else None
        if recipe and recipe.get('ffbe', {}).get('source'):
            key = recipe['ffbe']['source']
            selected = unit.setdefault('nativeImports', [])
            if key not in selected: selected.append(key)
            kits.remove(unit, group, str(grant[1]))
        else: unit['awakening'][tier].pop(index)
        return unit
    raise ValueError('Unknown grant action')
