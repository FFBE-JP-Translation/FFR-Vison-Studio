"""Build ALL picker forms from exact unit membership and reviewed source records.

The SQLite bundle is portable: Studio needs neither the 658k-row review database
nor the author's datamine. Each supported skill carries its structured sources.
"""
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'tools/devui')]
import ffbe_catalog
from ability_converter import commands, reviewed, multicast
from ability_converter.catalog import SourceCatalog
from tools.effect_review.conversion.run import current_folder


def blob(value):
    return zlib.compress(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode(), 3)


def rarity(value):
    text = str(value or 0)
    return 8 if text.startswith(('NV', 'EX')) else int(text)


def form_sources():
    """One exact unit owner per form; merged names never establish membership."""
    result = {}
    sources = ffbe_catalog.sources()
    live_rows = json.loads((ROOT/'build/devui/live_jp/F_UNIT_SERIES_LV_ACQUIRE_MST.json').read_text(encoding='utf-8'))['rows']
    live_skills = defaultdict(list)
    for row in live_rows:
        for column in ('ability_ids', 'magic_ids'):
            for sid in str(row.get(column) or '').split(','):
                if sid and sid != '0':
                    live_skills[str(row['unit_id'])].append({'id': sid, 'rarity': row['rarity_min'],
                        'level': row['level'], 'nv_level': row.get('nv_level'), 'ex_level': row.get('ex_level')})
    # Latest Global mechanics where present, then the current JP client and
    # older regional snapshots. The source revision is visible for every form.
    for region, source in [('GLW','GL_2024'), ('LIVE','JP_CLIENT'), ('JPW','JP_2024'), ('GL','GL_2022'), ('JP','JP_2022')]:
        leader_path = Path(ffbe_catalog.DATAMINE)/('gl' if region in ('GLW','GL') else 'jp')/'leader_skills.json'
        leaders = json.loads(leader_path.read_text(encoding='utf-8')) if leader_path.exists() else {}
        for uid, unit in sources.get(region, {}).get('units', {}).items():
            for form, entry in (unit.get('entries') or {}).items():
                if form in result: continue
                skills = live_skills[uid] if region == 'LIVE' else unit.get('skills', [])
                allowed = []
                for skill in skills:
                    if rarity(skill.get('rarity')) > rarity(entry.get('rarity')): continue
                    if int(skill.get('nv_level') or 0) > int(entry.get('nv_level') or 0): continue
                    allowed.append({**skill, 'origin': 'learned'})
                leader = entry.get('leader_skill_id')
                if leader and str(leader) != '0':
                    linked = leaders.get(str(leader), {})
                    allowed.append({'id': str(linked.get('skill_id', leader)), 'origin': 'leader',
                        'leaderId': str(leader), 'leaderCategories': linked.get('leader_skill_tag_ids', [])})
                result[form] = {'owner': uid, 'region': region, 'source': source, 'entry': entry, 'skills': allowed}
    return result


def build():
    started = time.monotonic()
    folder = current_folder()
    index = ffbe_catalog.load_index()
    forms = form_sources()
    target = ROOT/'data/ability_converter/vision-kits.sqlite'
    pending = target.with_suffix('.pending.sqlite')
    if pending.exists():
        raise ValueError(f'Previous incomplete bundle exists: {pending}; preserve or inspect it before retrying')
    counts = Counter(); problems = []; materials = Counter()
    source_keys = set()
    with SourceCatalog.open_existing(folder/'source-index.sqlite') as sources, closing(sqlite3.connect(folder/'report.sqlite')) as report, closing(sqlite3.connect(pending)) as out:
        out.executescript('''CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE kits(form TEXT PRIMARY KEY,unit_id TEXT,payload BLOB);
            CREATE TABLE profiles(source_key TEXT PRIMARY KEY,supported INTEGER,payload BLOB);''')
        decisions = dict(report.execute("SELECT source_key,notes FROM decisions WHERE status='changes'"))
        cache = {}

        def get_record(source, sid, kind='skill', max_level=None):
            rows = sources.connection.execute('SELECT source_key FROM records WHERE source=? AND scope=? AND source_id=? AND (? IS NULL OR level<=?) ORDER BY level DESC',
                (source, kind, str(sid), max_level, max_level)).fetchall()
            if kind == 'lb': rows = rows[:1]
            if len(rows) != 1: raise ValueError(f'{len(rows)} source matches for {source}/{kind}/{sid}')
            return sources.get(rows[0][0])

        def prepare(record):
            if record.key in cache: return cache[record.key]
            p = commands.profile(record, sources, reviewed=True)
            if record.key in decisions:
                p['supported'] = False; p['issues'].append('Marked for changes in the ability review: ' + decisions[record.key])
            if p['supported']:
                # Exercise the actual native row writer for EVERY supported
                # source, including child graphs and effect overflow allocation.
                tables = defaultdict(lambda: {'add': [], 'set': []})
                try:
                    commands.materialize(p, 51000 if record.kind == 'passive' else 485000, 'audit', lambda t: tables[t], lambda *args: ('audit', {}))
                    materials.update({t: len(v['add']) for t,v in tables.items()})
                except (ValueError, KeyError, TypeError, IndexError) as ex:
                    p['supported'] = False; p['issues'].append('Native table binding: ' + str(ex))
            conversion = p['conversion']
            name = (ffbe_catalog.en_lb(record.id) if record.kind == 'lb' else ffbe_catalog.en_skill(record.id)) or record.data.get('name') or record.id
            summary = {'id': int(record.id), 'kind': record.kind.upper(), 'name': name, 'sourceKey': record.key,
                'disabledBy':p.get('disabledBy'),
                'icon': conversion['presentation'].get('icon'), 'effects': record.data.get('effects') or [],
                'status': 'ready' if p['supported'] else 'held', 'class': 'partial' if conversion.get('partial') else 'reviewed' if p['supported'] else 'unsupported',
                'description': p.get('description') or conversion.get('summary', ''), 'issues': p['issues'],
                'changes': p['warnings'], 'source': conversion['source']}
            children = []
            for c in conversion['components']:
                for dep in c['dependencies']:
                    if dep.get('resolved') and dep.get('relation') not in ('tag', 'charge_pool'):
                        children.append(dep['resolved'])
            cache[record.key] = (summary, list(dict.fromkeys(children)))
            out.execute('INSERT INTO profiles VALUES (?,?,?)', (record.key, int(p['supported']), blob(p)))
            counts['uniqueSources'] += 1; counts['readySources' if p['supported'] else 'heldSources'] += 1
            if counts['uniqueSources'] % 1000 == 0:
                print(f"Prepared {counts['uniqueSources']:,} unique skills / {counts['forms']:,} forms", flush=True)
                out.commit()
            return cache[record.key]

        enhancements = defaultdict(list)
        for region, source in [('gl','GL_2024'), ('jp','JP_2024')]:
            path = Path(ffbe_catalog.DATAMINE)/region/'enhancements.json'
            if path.exists():
                for value in json.loads(path.read_text(encoding='utf-8')).values():
                    for form in value.get('units') or []:
                        enhancements[source, str(form)].append(value)
        for unit in index:
            for form in unit['forms']:
                if out.execute('SELECT 1 FROM kits WHERE form=?', (form,)).fetchone(): continue
                origin = forms.get(form)
                kit = {'form': form, 'unitId': unit['id'], 'name': unit['name'], 'policy': reviewed.VERSION, 'entries': [], 'issues': []}
                if origin is None:
                    kit['issues'].append('No exact source unit entry exists for this look')
                    problems.append({'form': form, 'reason': kit['issues'][0]})
                else:
                    kit.update(region=origin['region'], source=origin['source'], owner=origin['owner'])
                    pending_records = []; seen = set()
                    for skill in origin['skills']:
                        try: pending_records.append((get_record(origin['source'], skill['id']), skill))
                        except ValueError as ex:
                            kit['entries'].append({'id': int(skill['id']), 'kind': 'UNKNOWN', 'name': ffbe_catalog.en_skill(skill['id']) or str(skill['id']),
                                'sourceKey': f"{origin['source']}/missing/{skill['id']}", 'status': 'held', 'issues': [str(ex)], 'origin': skill['origin']})
                            counts['missingReferences'] += 1
                    # All enhancement levels stay selectable, instead of
                    # silently substituting the newest move for the base move.
                    for enhancement in enhancements[origin['source'], form]:
                        try: pending_records.append((get_record(origin['source'], enhancement['skill_id_new']), {'origin': 'enhancement', 'replaces': enhancement['skill_id_old']}))
                        except ValueError as ex: kit['issues'].append(str(ex))
                    lbs = origin['entry'].get('limitburst_id') or []
                    for lb in lbs if isinstance(lbs, list) else [lbs]:
                        if str(lb) == '0': continue
                        try: pending_records.append((get_record(origin['source'], lb, 'lb', origin['entry'].get('lb_max_level') or None), {'origin': 'limit_burst'}))
                        except ValueError as ex: kit['issues'].append(str(ex))
                    pos = 0
                    while pos < len(pending_records):
                        record, membership = pending_records[pos]; pos += 1
                        if record.key in seen: continue
                        seen.add(record.key); source_keys.add(record.key)
                        summary, children = prepare(record)
                        kit['entries'].append({**summary, **{k: v for k,v in membership.items() if k not in ('id','type')}})
                        for key in children:
                            if key not in seen:
                                pending_records.append((sources.get(key), {'origin': 'linked', 'parent': record.key}))
                out.execute('INSERT INTO kits VALUES (?,?,?)', (form, unit['id'], blob(kit)))
                counts['forms'] += 1; counts['memberships'] += len(kit['entries'])
                counts['emptyForms'] += not kit['entries']
                counts['readyMemberships'] += sum(e['status'] == 'ready' for e in kit['entries'])
                counts['heldMemberships'] += sum(e['status'] != 'ready' for e in kit['entries'])
            counts['visions'] += 1
        expected = {f for u in index for f in u['forms']}
        actual = {r[0] for r in out.execute('SELECT form FROM kits')}
        assert actual == expected, (expected-actual, actual-expected)
        for key, value in {'version': reviewed.VERSION, 'rulesSha256': reviewed.fingerprint(), 'studioPolicy':multicast.VERSION, 'report': str(folder), 'counts': json.dumps(counts)}.items():
            out.execute('INSERT INTO metadata VALUES (?,?)', (key, value))
        out.commit()
    pending.replace(target)
    audit = {'counts': dict(counts), 'allPickerFormsCovered': True, 'sourceProblems': problems,
        'materializedRows': dict(materials), 'elapsedSeconds': round(time.monotonic()-started),
        'policy': reviewed.VERSION, 'rulesSha256': reviewed.fingerprint(), 'sourceReport': str(folder),
        'runtimeValidation': 'awaiting_user_gameplay_testing'}
    (target.parent/'vision-kits-audit.json').write_text(json.dumps(audit, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(audit, indent=2), flush=True)


if __name__ == '__main__': build()
