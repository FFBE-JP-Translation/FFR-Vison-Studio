"""Freeze the user-reviewed mappings and index the entire corpus once."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from tools.ability_converter.catalog import SourceCatalog
from tools.effect_review.sources import iter_complete_sources
from tools.effect_review.serve import DIRECTORY, validate_review

ROOT = DIRECTORY.parents[1]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    catalog = json.loads((DIRECTORY/'catalog.json').read_text(encoding='utf-8'))
    saved = json.loads((DIRECTORY/'review-decisions.json').read_text(encoding='utf-8'))
    decisions = validate_review(saved, catalog)
    for name, meta in catalog['sources'].items():
        if digest(name) != meta['sha256']:
            raise ValueError(f'Source snapshot changed: {name}')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder = ROOT/'build/ability-review'/stamp
    folder.mkdir(parents=True, exist_ok=False)
    approval = {'method': 'conversation', 'message': "i think i'm done", 'savedRevision': decisions['revision'],
                'originalStage': decisions['stage'], 'originalUnchecked': [k for k,v in decisions['decisions'].items() if not v['reviewed']],
                'note': 'The user completed review in conversation; preserve their unchecked flags and all unresolved Other choices for report accounting.'}
    write(folder/'review-snapshot.json', {**decisions, 'approval': approval})
    write(folder/'run.json', {'status': 'indexing', 'expectedRecords': catalog['coverage']['totalRecords'], 'createdAt': stamp})
    write(folder/'source-manifest.json', catalog['sources'])
    write(folder/'catalog-snapshot.json', catalog)
    with SourceCatalog(folder/'source-index.sqlite') as index:
        for record in iter_complete_sources():
            index.add(record)
            if index.count % 50000 == 0:
                print(f'Indexed {index.count:,} / {catalog["coverage"]["totalRecords"]:,} source records', flush=True)
                index.finish()
        index.finish()
        assert index.count == catalog['coverage']['totalRecords']
        write(folder/'run.json', {'status': 'indexed', 'records': index.count, 'expectedRecords': index.count, 'createdAt': stamp})
    write(ROOT/'build/ability-review/current.json', {'directory': str(folder)})
    print(str(folder), flush=True)


if __name__ == '__main__':
    main()
