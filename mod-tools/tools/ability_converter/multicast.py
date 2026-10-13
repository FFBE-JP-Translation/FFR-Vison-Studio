"""Temporary Studio policy: multicast selection is not implemented in FFR."""
VERSION = 'no-multicast/1'
REASON = 'Multicast is disabled until FFR can offer the required ability selections.'


def component(namespace, raw):
    if not isinstance(raw, list) or len(raw) != 4: return False
    code, params = raw[2:]
    if namespace == 'passive': return code in (52, 53, 102)
    if namespace != 'active': return False
    return code in (44, 45, 97, 98, 168, 1006) or (
        code == 102 and isinstance(params,list) and len(params) > 3 and params[3] is not None)


def in_snapshot(snapshot):
    return any(component('passive' if r['kind'] == 'passive' else 'active', raw)
               for r in snapshot.get('records', []) for raw in (r['data'].get('effects_raw') or []))


def remove_disabled_grants(unit, disabled_keys=None):
    """Archive obsolete pure multicast grants, including old saved loadouts."""
    from copy import deepcopy
    from .commands import from_spec
    for group,kind in (('skills','ActiveSkill'),('convertedPassives','PassiveSkill')):
        for sid,recipe in list(unit.get(group,{}).items()):
            if recipe.get('mechanics') != 'converted': continue
            if disabled_keys is not None:
                if recipe.get('ffbe',{}).get('source') not in disabled_keys: continue
            else:
                if not in_snapshot(recipe.get('conversionSource',{})): continue
                profile = from_spec(recipe)
                if profile.get('disabledBy') != 'multicast': continue
            unit.setdefault('conversionArchive',[]).append({'group':group,'id':str(sid),'entry':deepcopy(recipe),
                'awakening':deepcopy(unit.get('awakening')), 'synchro':deepcopy(unit.get('synchro')), 'reason':REASON})
            del unit[group][sid]
            for field in ('awakening','synchro'):
                for grants in unit.get(field,[]): grants[:] = [g for g in grants if tuple(g[:2]) != (kind,int(sid))]
            source = recipe.get('ffbe',{}).get('source')
            unit['nativeImports'] = [key for key in unit.get('nativeImports',[]) if key != source]
            mapping = unit.get('ffbeMap',{}).get('skills' if group == 'skills' else 'passives',{})
            for key,value in list(mapping.items()):
                if value == int(sid) or isinstance(value,dict) and value.get('grant') == [kind,int(sid)]: del mapping[key]
    return unit
