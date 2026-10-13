"""The approved shared-effect rules used by Studio and reproducible builds."""
from functools import lru_cache
from copy import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
RULES_PATH = ROOT / 'data/ability_converter/reviewed-rules.json'
VERSION = 'ffbe-ffr-reviewed/203.1'


@lru_cache(maxsize=1)
def rules():
    payload = json.loads(RULES_PATH.read_text(encoding='utf-8'))
    if payload['savedRevision'] != 203 or len(payload['rules']) != 346:
        raise ValueError('The approved effect rule bundle is incomplete')
    return payload['rules']


def fingerprint():
    return hashlib.sha256(RULES_PATH.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _template():
    from tools.effect_review.conversion.engine import ReviewedConverter
    return ReviewedConverter(rules())


def compiler(resolver):
    instance = copy(_template())
    instance.resolver = resolver
    return instance


def decisions(profile):
    return [{'key': c.get('key'), 'label': rules().get(c.get('key'), {}).get('label', 'Unknown effect'),
             'class': 'omitted' if not c['effects'] and not c['actions'] else 'reviewed',
             'issues': [v['reason'] for v in c.get('omissions', [])], 'options': [],
             'suggestion': rules().get(c.get('key'), {}).get('implementation', '')}
            for c in profile['conversion']['components']]
