"""Distinguish source upgrade chains from the linked actions they execute."""
def decorate(entries):
    by_key = {e['sourceKey']:e for e in entries}
    by_id = {(e['sourceKey'].split('/')[0], str(e['id'])):e for e in entries}

    def ancestry(entry, seen=None):
        seen = set() if seen is None else seen
        if entry['sourceKey'] in seen: return entry, 0
        seen.add(entry['sourceKey'])
        previous = by_id.get((entry['sourceKey'].split('/')[0], str(entry.get('replaces'))))
        if previous:
            root, rank = ancestry(previous, seen)
            return root, rank+1
        if entry.get('origin') == 'linked':
            parent = by_key.get(entry.get('parent'))
            if parent and parent['name'] == entry['name']:
                return ancestry(parent, seen)
        return entry, 0

    families = {}
    for entry in entries:
        root, rank = ancestry(entry)
        entry.update(variantFamily=root['sourceKey'], upgradeLevel=rank)
        parent = by_key.get(entry.get('parent'))
        same_action = entry.get('origin') == 'linked' and parent and parent['name'] == entry['name']
        entry['componentOf'] = parent['sourceKey'] if same_action else None
        families.setdefault(root['sourceKey'], []).append(entry)
    for family in families.values():
        upgraded = any(e['upgradeLevel'] for e in family)
        for entry in family:
            label = f"Upgrade +{entry['upgradeLevel']}" if entry['upgradeLevel'] else 'Base version' if upgraded else ''
            if entry['componentOf']: label = ' · '.join(filter(None,[label,'Linked action']))
            elif entry.get('origin') == 'linked': label = ' · '.join(filter(None,[label,'Unlocked action']))
            entry['variantLabel'] = label
    return entries


def strongest(entries, group):
    decorate(entries)
    by_key = {e['sourceKey']:e for e in entries}
    chosen = {}
    for entry in entries:
        if entry.get('disabledBy') == 'multicast': continue
        if entry['kind'] == 'LB' or (entry['kind'] == 'PASSIVE') != (group == 'bonuses'): continue
        if entry.get('componentOf') and by_key.get(entry['componentOf'],{}).get('status') == 'ready': continue
        family = entry['variantFamily']
        rank = (entry['status'] == 'ready', entry['upgradeLevel'], not bool(entry.get('componentOf')))
        old = chosen.get(family)
        if old is None or rank > old[0]: chosen[family] = (rank,entry)
    return [e for _,e in chosen.values()]
