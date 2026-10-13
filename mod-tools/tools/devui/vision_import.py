"""Reviewed form kits plus a reversible, native-sized gameplay testing loadout."""
from copy import deepcopy
import os

import ffbe_catalog
import reviewed_kits
import skill_icons
import native_variants
from ability_converter import commands, reviewed
from ability_converter.skill_ids import vision_passive_base


def imported(unit, key):
    for group in ('skills', 'convertedPassives'):
        for sid, recipe in unit.get(group, {}).items():
            if recipe.get('ffbe', {}).get('source') == key: return group, sid
    if unit.get('lb_custom', {}).get('ffbe', {}).get('source') == key: return 'lb_custom', 'resonance'
    return None


def remove(unit, group, sid):
    if group not in ('skills', 'convertedPassives'): raise ValueError('Choose an ordinary ability or passive to remove')
    recipe = unit.get(group, {}).get(str(sid))
    if recipe is None: raise ValueError('The selected loadout slot no longer exists')
    kind = 'ActiveSkill' if group == 'skills' else 'PassiveSkill'
    for field in ('awakening', 'synchro'):
        for grants in unit.get(field, []):
            grants[:] = [g for g in grants if g[:2] != [kind, int(sid)]]
    del unit[group][str(sid)]
    mapping = unit.get('ffbeMap', {}).get('skills' if group == 'skills' else 'passives', {})
    for key, value in list(mapping.items()):
        if value == int(sid) or isinstance(value, dict) and value.get('grant') == [kind, int(sid)]: del mapping[key]


def equip(unit, key, replace_id=None, target_tier=None, *, prepare_effects=True):
    entry = next((e for e in unit.get('ffbeLibrary', []) if e['sourceKey'] == key), None)
    if entry is None: raise ValueError('That ability is not in this form’s imported kit')
    if entry['status'] != 'ready': raise ValueError('; '.join(entry.get('issues') or ['This ability has no compatible mechanics']))
    if prepare_effects and entry['kind'] != 'PASSIVE':
        import effect_downloads
        effect_downloads.ensure_move(str(unit['ffbe']['id']), key)
    if imported(unit, key): return unit
    p = deepcopy(reviewed_kits.profile(key, unit['ffbe']['id']))
    if not p['supported']: raise ValueError('; '.join(p['issues']))
    passive = entry['kind'] == 'PASSIVE'
    group = 'convertedPassives' if passive else 'skills'
    if replace_id is not None:
        previous = unit.get(group, {}).get(str(replace_id))
        if previous and previous.get('mechanics') != 'converted':
            unit.setdefault('conversionArchive', []).append({'group': group, 'id': str(replace_id),
                'entry': deepcopy(previous), 'awakening': deepcopy(unit.get('awakening')), 'reason': 'Replaced in testing loadout'})
        remove(unit, group, str(replace_id))
    unit.setdefault(group, {})
    unit.setdefault('awakening', [[], [], [], []])
    base = vision_passive_base(unit['id']) if passive else 445000 + (unit['id']-13100)*100
    full_kit = unit.get('fullKit') is True
    slots = list(range(base, base+100, 1 if passive or full_kit else 10))
    sid = next((sid for sid in slots if str(sid) not in unit[group]), None)
    from autoport import add_grant, tier_for
    if entry['kind'] != 'LB':
        if sid is None: raise ValueError('The testing loadout is full. Choose a move to replace; every move stays in the imported kit.')
        if target_tier is not None and (type(target_tier) is not int or not 0 <= target_tier < 4):
            raise ValueError('Choose an awakening tier from 1 to 4')
        if not full_kit and target_tier is not None and len(unit['awakening'][target_tier]) >= 8:
            raise ValueError('This awakening tier is full. Move a grant to another tier first.')
        if full_kit:
            tier = target_tier if target_tier is not None else 0
            unit['awakening'][tier].append(['PassiveSkill' if passive else 'ActiveSkill', sid])
        else:
            tier = add_grant(unit, target_tier if target_tier is not None else tier_for(entry.get('level')), ['PassiveSkill' if passive else 'ActiveSkill', sid])
        if tier is None: raise ValueError('All awakening grant slots are full. Remove a grant or replace an equipped move.')
    else:
        sid = 440000 + (unit['id']-13099)*10
    icon = entry.get('icon')
    icon = os.path.basename(icon.replace('\\','/')) if isinstance(icon, str) else None
    recipe = {'mechanics': 'converted', 'effectPolicy': reviewed.VERSION, 'conversionSource': p['snapshot'],
        'conversionClass': entry['class'], 'conversionChanges': p['warnings'], 'conversionDecisions': reviewed.decisions(p),
        'jp': f"{unit['jp']}_FFBE_{sid}", 'en': entry['name'], 'desc': p['description'], 'descAuto': True,
        'ffbe': {'id': entry['id'], 'kind': entry['kind'], 'source': key, 'name': entry['name'],
                 'effects': entry.get('effects', []), 'icon': icon, 'iconUrl': f'/api/ffbe/abilityicon/{icon}' if icon else None}}
    if not passive:
        if full_kit: recipe['fullKitSequence'] = True
        native = commands.converter().native
        donor = next(i for i,name in native.skill_ids.items() if name == p['conversion']['native']['cloneFrom'])
        recipe.update({'from': donor, 'motion': 'attack_A' if p['set']['DamageType'] == 'Physic' else 'magic_attack', 'set': p['set']})
    else:
        recipe['set'] = {k: v for k, v in p.get('set', {}).items() if k in ('equipCost', 'SkillIcon.TagName')}
    if icon and skill_icons.path(icon):
        recipe['set']['SkillIcon.TagName'] = skill_icons.tag(icon)
    edits = unit.get('nativeEdits', {}).get(key)
    if edits: apply_edits(recipe, edits, passive)
    if not passive and unit.get('testingMPCost') is not None:
        recipe.setdefault('set', {})['Cost'] = int(unit['testingMPCost'])
    if entry['kind'] == 'LB':
        if unit.get('lb_custom'):
            unit.setdefault('conversionArchive', []).append({'group': 'lb_custom', 'entry': unit['lb_custom']})
        recipe.update(presentation='ffbe', field_color_mode='element', audio='native', audio_codec='host', ffbe_lb_id=str(entry['id']))
        unit['lb_custom'] = recipe
        return unit
    unit[group][str(sid)] = recipe
    maps = unit.setdefault('ffbeMap', {})
    maps.setdefault('passives' if passive else 'skills', {})[str(entry['id'])] = (
        {'tier': tier, 'grant': ['PassiveSkill', sid], 'name': entry['name']} if passive else sid)
    return unit


def initialize_native_loadout(unit):
    """Seed a newly added vision once; later opening it preserves user edits.

    Full-kit sequences have their own ID range, so adjacent command slots are
    safe. Effect media is prepared by the build job, not by the unit-add request.
    """
    if unit.get('nativeLoadoutVersion') == 1:
        return unit
    draft = deepcopy(unit)
    hydrate(draft)
    draft['fullKit'] = True
    selected = [entry for group in ('abilities', 'bonuses')
                for entry in native_variants.strongest(draft['ffbeLibrary'], group)]
    draft['nativeImports'] = [entry['sourceKey'] for entry in selected]
    for entry in selected:
        if entry['status'] == 'ready':
            equip(draft, entry['sourceKey'], prepare_effects=False)
    for recipe in draft['skills'].values():
        recipe['fullKitSequence'] = True

    # Balance each category separately, using total grants to break ties. This
    # also balances the combined list when either category has a remainder.
    awakening = draft['awakening']
    categories = {kind: [g for tier in awakening for g in tier if g[0] == kind]
                  for kind in ('ActiveSkill', 'PassiveSkill')}
    for tier in awakening:
        tier[:] = [g for g in tier if g[0] not in categories]
    for kind, grants in categories.items():
        counts = [0] * 4
        for grant in grants:
            tier = min(range(4), key=lambda t: (counts[t], len(awakening[t]), t))
            awakening[tier].append(grant)
            counts[tier] += 1
            for value in draft.get('ffbeMap', {}).get('passives', {}).values():
                if isinstance(value, dict) and value.get('grant') == grant:
                    value['tier'] = tier
    draft['nativeLoadoutVersion'] = 1
    unit.clear()
    unit.update(draft)
    return unit


def hydrate(unit, cat=None, detail=None):
    if unit.get('custom'): return unit
    from ability_converter.multicast import remove_disabled_grants
    form = str(unit['ffbe']['id'])
    if unit.get('ffbeKit', {}).get('policy') == reviewed.VERSION and unit['ffbeKit'].get('form') == form and unit.get('nativeLibraryVersion') == 2:
        native_variants.decorate(unit.get('ffbeLibrary', []))
        import effect_downloads
        effect_downloads.decorate_rows(form, unit.get('ffbeLibrary', []))
        return unit
    data = reviewed_kits.entries(unit)
    disabled = {e['sourceKey'] for e in data['entries'] if e.get('disabledBy') == 'multicast'}
    remove_disabled_grants(unit, disabled)
    # Historical imports are retained in the archive. Authored FFR recipes and
    # native grants stay intact; the new kit uses its own remaining slots.
    for group in ('skills', 'convertedPassives'):
        for sid, recipe in list(unit.get(group, {}).items()):
            if recipe.get('mechanics') != 'converted': continue
            key = recipe.get('ffbe', {}).get('source')
            if key not in disabled and recipe.get('effectPolicy') == reviewed.VERSION and any(e['sourceKey'] == key for e in data['entries']):
                profile = reviewed_kits.profile(key, form)
                if profile.get('supported') and recipe.get('descAuto', True): recipe['desc'] = profile['description']
                continue
            unit.setdefault('conversionArchive', []).append({'group': group, 'id': sid, 'entry': deepcopy(recipe),
                'awakening': deepcopy(unit.get('awakening')), 'synchro': deepcopy(unit.get('synchro'))})
            remove(unit, group, sid)
    unit['nativeImports'] = [key for key in unit.get('nativeImports', []) if key not in disabled]
    unit['ffbeLibrary'] = deepcopy([e for e in data['entries'] if e['sourceKey'] not in disabled])
    native_variants.decorate(unit['ffbeLibrary'])
    for entry in unit['ffbeLibrary']:
        p = reviewed_kits.profile(entry['sourceKey'], form)
        settings = p.get('set', {})
        entry.update(cost=settings.get('equipCost' if entry['kind'] == 'PASSIVE' else 'Cost', 0),
                     ffrIcon=settings.get('SkillIcon.TagName'))
    unit['nativeLibraryVersion'] = 2
    import effect_downloads
    effect_downloads.decorate_rows(form, unit['ffbeLibrary'])
    unit['ffbeKit'] = {k: v for k,v in data.items() if k != 'entries'}
    unit['effectPolicy'] = reviewed.VERSION
    unit['conversionReview'] = [e for e in data['entries'] if e['status'] != 'ready' and e['sourceKey'] not in disabled]
    # Opening a vision fills the native library. Importing into awakening tiers
    # is an explicit editor action; existing grants remain unchanged.
    for entry in data['entries']:
        if entry['kind'] == 'LB' and entry['status'] == 'ready' and not unit.get('lb_custom'):
            equip(unit, entry['sourceKey'])
    return unit


def import_native(unit, group):
    if group not in ('abilities', 'bonuses'): raise ValueError('Choose abilities or bonuses')
    hydrate(unit)
    draft = deepcopy(unit)
    selected = draft.setdefault('nativeImports', [])
    entries = draft.get('ffbeLibrary', [])
    recommendations = native_variants.strongest(entries, group)
    # Replace older imported versions within their existing tier/slot. Explicit
    # imports request the strongest version; merely opening a vision does not.
    for entry in recommendations:
        key = entry['sourceKey']
        if key not in selected: selected.append(key)
        if entry['status'] != 'ready': continue
        older = []
        for old in entries:
            if old['sourceKey'] == key or old.get('variantFamily') != entry['variantFamily']: continue
            found = imported(draft, old['sourceKey'])
            if found and found[0] in ('skills','convertedPassives'):
                older.append((old, found))
        old_grants = {('ActiveSkill' if found[0] == 'skills' else 'PassiveSkill', int(found[1])) for _,found in older}
        anchor = next(((field,tier,index) for field in ('awakening','synchro')
                       for tier,grants in enumerate(draft.get(field, [])) for index,grant in enumerate(grants)
                       if tuple(grant[:2]) in old_grants), None)
        already_equipped = imported(draft, key)
        for old, found in older:
            draft.setdefault('conversionArchive', []).append({'group':found[0], 'id':found[1],
                'entry':deepcopy(draft[found[0]][found[1]]), 'awakening':deepcopy(draft.get('awakening')),
                'synchro':deepcopy(draft.get('synchro')), 'reason':'Replaced by strongest native upgrade'})
            remove(draft, *found)
            if old['sourceKey'] in selected: selected.remove(old['sourceKey'])
        try:
            equip(draft, key, target_tier=anchor[1] if anchor and anchor[0] == 'awakening' else None)
        except ValueError as ex:
            if older or not any(s in str(ex) for s in ('loadout is full', 'grant slots are full')): raise
            continue
        if anchor and not already_equipped:
            recipe_group, sid = imported(draft, key)
            grant = ['ActiveSkill' if recipe_group == 'skills' else 'PassiveSkill', int(sid)]
            for field in ('awakening','synchro'):
                for grants in draft.get(field, []): grants[:] = [g for g in grants if g[:2] != grant]
            field,tier,index = anchor
            draft[field][tier].insert(index, grant)
    unit.clear()
    unit.update(draft)
    return unit


def apply_edits(recipe, edits, passive=False):
    recipe.update(en=edits['name'], desc=edits['description'], descAuto=False)
    recipe['iconChoice'] = edits['icon']
    recipe.setdefault('set', {})['equipCost' if passive else 'Cost'] = edits['cost']
    if edits['icon']: recipe['set']['SkillIcon.TagName'] = edits['icon']
    else:
        recipe['set'].pop('SkillIcon.TagName', None)
        if source := skill_icons.path(recipe.get('ffbe', {}).get('icon')):
            recipe['set']['SkillIcon.TagName'] = skill_icons.tag(source.name)


def preview(unit):
    data = reviewed_kits.entries(unit)
    rows = []
    for entry in data['entries']:
        found = imported(unit, entry['sourceKey'])
        icon = entry.get('icon')
        rows.append({**entry, 'icon': icon, 'importedId': found[1] if found else None,
            'decisions': [], 'ability': entry, 'inLibrary': any(e['sourceKey'] == entry['sourceKey'] for e in unit.get('ffbeLibrary', []))})
    import effect_downloads
    effect_downloads.decorate_rows(str(unit['ffbe']['id']), rows)
    return {**{k: v for k,v in data.items() if k != 'entries'}, 'entries': rows}
