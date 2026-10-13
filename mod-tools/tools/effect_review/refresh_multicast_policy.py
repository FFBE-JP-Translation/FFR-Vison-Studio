"""Bake the multicast removal into all prepared profiles and vision bundles."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT),str(ROOT/'tools'),str(ROOT/'tools/devui')]
from ability_converter import commands,multicast
import reviewed_kits


def blob(value):
    return zlib.compress(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode(),3)


def refresh():
    work = ROOT/'build/multicast-fix'/datetime.now().strftime('%Y%m%d_%H%M%S')
    work.mkdir(parents=True)
    staged = work/'vision-kits.sqlite'
    shutil.copy2(reviewed_kits.PATH,staged)
    stats = Counter(); changed = {}
    with sqlite3.connect(staged) as db:
        for key,payload in db.execute('SELECT source_key,payload FROM profiles').fetchall():
            old = json.loads(zlib.decompress(payload)); stats['profilesChecked'] += 1
            if not multicast.in_snapshot(old.get('snapshot',{})): continue
            p = commands.from_snapshot(old['snapshot'],reviewed=True)
            # An existing user review hold remains a hold after this removal.
            if not old['supported'] and p['supported']:
                p['supported'] = False
                p['issues'] = list(dict.fromkeys([*p['issues'],*old['issues']]))
            changed[key] = p
            db.execute('UPDATE profiles SET supported=?,payload=? WHERE source_key=?',(int(p['supported']),blob(p),key))
            stats['profilesRefreshed'] += 1
            stats['disabledProfiles'] += p.get('disabledBy') == 'multicast'
            if stats['profilesRefreshed'] % 100 == 0: print(dict(stats),flush=True)
        for form,payload in db.execute('SELECT form,payload FROM kits').fetchall():
            kit = json.loads(zlib.decompress(payload)); stats['forms'] += 1
            for entry in kit['entries']:
                p = changed.get(entry['sourceKey'])
                if p:
                    entry.update(status='ready' if p['supported'] else 'held', disabledBy=p.get('disabledBy'),
                        description=p.get('description') or p['conversion'].get('summary',''),
                        issues=p['issues'],changes=p['warnings'],
                        **{'class':'partial' if p['conversion'].get('partial') else 'reviewed' if p['supported'] else 'unsupported'})
                stats['readyMemberships' if entry['status'] == 'ready' else 'heldMemberships'] += 1
                stats['disabledMemberships'] += entry.get('disabledBy') == 'multicast'
            db.execute('UPDATE kits SET payload=? WHERE form=?',(blob(kit),form))
        metadata = dict(db.execute('SELECT key,value FROM metadata'))
        counts = json.loads(metadata['counts'])
        counts.update({k:stats[k] for k in ('readyMemberships','heldMemberships')})
        counts['readySources'] = db.execute('SELECT count(*) FROM profiles WHERE supported=1').fetchone()[0]
        counts['heldSources'] = stats['profilesChecked']-counts['readySources']
        db.execute('UPDATE metadata SET value=? WHERE key=?',(json.dumps(counts),'counts'))
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('studioPolicy',multicast.VERSION))
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    shutil.copy2(reviewed_kits.PATH,work/'previous-vision-kits.sqlite')
    shutil.copy2(staged,reviewed_kits.PATH)
    # Studio receives completed conversions even when opening an old .ffr.
    with reviewed_kits.connect() as db:
        for (form,) in db.execute('SELECT form FROM kits'):
            target = reviewed_kits.BUNDLES/f'{form}.json'
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(reviewed_kits.export_bundle(form,db),ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    (work/'report.json').write_text(json.dumps(dict(stats),indent=2),encoding='utf-8')
    print(json.dumps({'work':str(work),**stats},indent=2),flush=True)


if __name__ == '__main__': refresh()
