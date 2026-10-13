"""Search categories from source tags, with game_id filling older series gaps."""
from functools import lru_cache
import json
from pathlib import Path


@lru_cache(maxsize=1)
def labels():
    return json.loads(Path(__file__).with_name('unit_categories.json').read_text(encoding='utf-8'))


def unit_tags(unit):
    tags = unit.get('tags') or []
    if isinstance(tags, str):
        tags = tags.split(',')
    result = {str(t) for t in tags if str(t) in labels()}
    game = str(unit.get('game_id') or '')
    # Only the original FF I-XVI / BE / Tactics / Type-0 tag IDs mirror
    # game IDs. Later category IDs use a different numbering scheme.
    series = '300' + game if game.isdigit() and (10001 <= int(game) <= 10016 or 11001 <= int(game) <= 11003) else None
    if series:
        result.add(series)
    elif 'game:' + game in labels():
        result.add('game:' + game)
    parent = {'11004': '30010010', '11005': '30010012', '11006': '30010013', '11007': '30010013',
              '11008': '30010004', '11009': '30010007', '11012': '30010007', '11010': '40000021'}.get(game)
    if parent:
        result.add(parent)
    return result


def enrich(index, sources, live_rows=()):
    by_form = {str(r.get('unit_evo_id')): r for r in live_rows}
    for row in index:
        tags = set()
        for uid in [row['id'], row.get('pairOf'), *(row.get('mergedIds') or [])]:
            for tables in sources.values():
                tags.update(unit_tags(tables.get('units', {}).get(uid, {})))
        for fid in row.get('forms', []):
            tags.update(unit_tags(by_form.get(str(fid), {})))
        row['categories'] = sorted(tags)
    return index
