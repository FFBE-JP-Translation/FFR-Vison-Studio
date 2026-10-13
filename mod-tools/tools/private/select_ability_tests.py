"""Choose real catalog records for a manually played mechanics-category pack."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from ability_converter import commands
from ability_converter.catalog import SourceCatalog

OUT = ROOT/'build/ability-test-visions'
LABELS = {'converted':'direct', 'adapted':'adaptation', 'replaced':'replacement'}

def write(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf8')

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    families = defaultdict(Counter)
    candidates = defaultdict(list)
    blocked = defaultdict(Counter)
    with (ROOT/'build/abilities/delivery/catalog/converted.jsonl').open(encoding='utf8') as stream:
        for number, raw in enumerate(stream, 1):
            r = json.loads(raw)
            fs = {c.get('family') or 'unclassified' for c in r['components']}
            for family in fs:
                families[family][r['status']] += 1
                if r['status']=='blocked':
                    blocked[family].update(r['issues'])
            if r['source']['kind'] not in ('ability','magic','passive') or r['status'] not in LABELS:
                continue
            score = (len(r['components']), 0 if r['source']['source']=='GL_2024' else 1,
                     0 if r['source']['source'].startswith('GL') else 1,
                     len(r['name']), r['source']['key'])
            item = (score, r['source']['key'])
            for family in fs-{'no_op','unclassified'}:
                pool = candidates[family]
                if len(pool)<100 or score<pool[-1][0]:
                    pool.append(item); pool.sort(); del pool[100:]
            if number%100000==0:print(f'Catalog selection: {number:,} records', flush=True)
    profiles = {}
    selected = {}
    exclusions = {}
    with SourceCatalog.open_existing(ROOT/'build/abilities/v1/source-index.sqlite') as catalog:
        for family in sorted(families):
            already = [k for k,p in selected.items() if family in p['testFamilies']]
            if already:continue
            failures = Counter()
            for _, key in candidates[family]:
                if key not in profiles:
                    profiles[key] = commands.profile(catalog.get(key), catalog)
                p = profiles[key]
                if not p['supported']:
                    failures.update(p['issues']); continue
                p = dict(p)
                p['testFamilies'] = sorted({c.get('family') or 'unclassified' for c in p['conversion']['components']}-{'no_op'})
                p['testClassification'] = LABELS[p['conversion']['status']]
                selected[key] = p
                break
            else:
                exclusions[family] = {'reason':'No runnable ordinary-command/passive representative found in the existing bindings.',
                    'candidateFailures':dict(failures.most_common(5)),
                    'catalogBlockers':dict(blocked[family].most_common(3)),
                    'catalogRecordOutcomes':dict(families[family])}
        # Ensure the three conversion classes can be compared independently.
        for key in ('GL_2024/magic/10010','GL_2024/magic/10020','GL_2024/magic/10060'):
            p=commands.profile(catalog.get(key), catalog)
            if p['supported']:
                p['testFamilies']=sorted({c['family'] for c in p['conversion']['components']})
                p['testClassification']=LABELS[p['conversion']['status']]
                selected[key]=p
    covered = {f for p in selected.values() for f in p['testFamilies']}
    exclusions = {f:v for f,v in exclusions.items() if f not in covered}
    write('selected-profiles.json', list(selected.values()))
    summary={'sourceRecordsScanned':number, 'selectedRecords':len(selected),
        'activeCommands':sum(p['conversion']['source']['kind']!='passive' for p in selected.values()),
        'passives':sum(p['conversion']['source']['kind']=='passive' for p in selected.values()),
        'classifications':dict(Counter(p['testClassification'] for p in selected.values())),
        'coveredFamilies':sorted(covered),'excludedFamilies':exclusions,
        'scope':'One representative per available mechanic family; not every opcode, target variant or source ability.',
        'gameplayValidation':'awaiting manual user testing'}
    write('selection.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
