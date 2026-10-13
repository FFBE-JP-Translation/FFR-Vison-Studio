"""English FFBE Limit Burst display names.

LB IDs are the primary key.  A fallback by exact Japanese name is provided for
legacy rows that do not retain an ID, but it is intentionally used only after
the supplied ID/name pair has been checked.  This prevents an alternate LB on
the same form from inheriting the form's default LB name.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


DATA = Path(__file__).with_name("lb_names.json")


@lru_cache(maxsize=1)
def translations():
    """Return the generated, package-safe LB translation table."""
    with DATA.open(encoding="utf-8") as handle:
        return json.load(handle)


def english_name(lb_id=None, name=None):
    """Return an English LB name for an exact ID/name pair, or ``None``.

    ``name`` should be the selected LB row's name, never the form or unit name.
    With a name supplied, an ID value is accepted only when that exact Japanese
    source name is recorded for the ID.  This keeps a form with several LB IDs
    from accidentally displaying the first/default LB's English title.
    """
    data = translations()
    if lb_id is not None:
        names = (data.get("byId") or {}).get(str(lb_id)) or {}
        if name is not None:
            hit = names.get(str(name))
            if hit:
                return hit
        elif len(names) == 1:
            return next(iter(names.values()))
    if name is not None:
        return (data.get("byName") or {}).get(str(name))
    return None
