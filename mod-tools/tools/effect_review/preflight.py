"""Validate review coverage and source hashes before the later full conversion.

This command only reads. It does not convert, create abilities or install mods.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .serve import DIRECTORY, ReviewError, validate_review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decisions', type=Path, default=DIRECTORY/'review-decisions.json')
    parser.add_argument('--require-ready', action='store_true')
    args = parser.parse_args()
    catalog = json.loads((DIRECTORY/'catalog.json').read_text(encoding='utf-8'))
    if not args.decisions.exists():
        raise SystemExit('No saved review yet. Open Effect Review.cmd and save your decisions first.')
    try:
        review = validate_review(json.loads(args.decisions.read_text(encoding='utf-8')), catalog)
    except (ReviewError, ValueError) as error:
        raise SystemExit(str(error))
    mismatches = []
    for name, info in catalog['sources'].items():
        path = Path(name)
        if not path.is_file():
            mismatches.append({'path': name, 'issue': 'missing'})
            continue
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != info['sha256']:
            mismatches.append({'path': name, 'issue': 'content changed'})
    pending = [key for key, value in review['decisions'].items() if not value['reviewed']]
    result = {'stage': review['stage'], 'reviewed': len(review['decisions'])-len(pending),
              'totalEffects': len(review['decisions']), 'recordsForFullRun': catalog['coverage']['totalRecords'],
              'sourceMismatches': mismatches, 'conversionRun': 'not_run'}
    print(json.dumps(result, indent=2))
    if mismatches:
        raise SystemExit('Source snapshot changed. Reconcile the inventory with the saved decisions before conversion.')
    if args.require_ready and review['stage'] != 'ready':
        raise SystemExit('Mapping review is not finished. No conversion was run.')


if __name__ == '__main__':
    main()
