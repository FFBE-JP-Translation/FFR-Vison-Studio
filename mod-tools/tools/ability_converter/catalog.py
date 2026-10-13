"""Disk-backed source catalog for deterministic, revision-scoped references.

The source formatter uses a separate MonsterSkillMstList. Equal player/enemy
IDs are therefore different namespaces, not ambiguous versions of one skill.
"""
from dataclasses import asdict
import json
import sqlite3
from pathlib import Path

from .sources import SourceRecord


def reference_scope(source, kind):
    if kind in ("lb", "field"):
        return kind
    return "enemy" if source["kind"] == "enemy" else "skill"


def record_scope(source):
    return source["kind"] if source["kind"] in ("lb", "field", "enemy") else "skill"


class SourceCatalog:
    @classmethod
    def open_existing(cls, path):
        """Open a completed run for resolution without rebuilding its index."""
        catalog = cls.__new__(cls)
        catalog.connection = sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro", uri=True)
        try:
            catalog.count = catalog.connection.execute("SELECT count(*) FROM records").fetchone()[0]
        except Exception:
            catalog.connection.close()
            raise
        catalog.paths = set()
        return catalog

    def get(self, key):
        row = self.connection.execute("SELECT payload FROM records WHERE source_key=?", (key,)).fetchone()
        if row is None:
            raise ValueError(f"No source record matches exact identity {key}")
        return SourceRecord(**json.loads(row[0]))

    def __init__(self, path=":memory:"):
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("PRAGMA cache_size=-16384")
        # A newly built catalog belongs to one run, never a union of revisions
        # accidentally left over from an earlier selection of source inputs.
        self.connection.executescript("""
            DROP TABLE IF EXISTS records;
            CREATE TABLE records (
                ordinal INTEGER PRIMARY KEY, source_key TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL, scope TEXT NOT NULL, source_id TEXT NOT NULL,
                level INTEGER, provenance TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE INDEX reference_lookup ON records (source, scope, source_id);
        """)
        self.count = 0
        self.paths = set()

    def add(self, record):
        provenance = record.provenance()
        try:
            self.connection.execute("INSERT INTO records VALUES (?,?,?,?,?,?,?,?)", (
                self.count, record.key, record.source, record_scope(provenance), record.id,
                int(record.level) if record.level is not None else None,
                json.dumps(provenance, ensure_ascii=False),
                json.dumps(asdict(record), ensure_ascii=False, separators=(",", ":"))))
        except sqlite3.IntegrityError as ex:
            raise ValueError(f"Duplicate source identity {record.key}") from ex
        self.count += 1
        self.paths.add(record.path.split("!", 1)[0])

    def finish(self):
        self.connection.commit()

    def __iter__(self):
        for (payload,) in self.connection.execute("SELECT payload FROM records ORDER BY ordinal"):
            yield SourceRecord(**json.loads(payload))

    def candidates(self, source, dependency):
        if dependency.get('relation')=='tag':
            # Tag grants name affected skills/LBs; they do not execute them.
            # A self tag belongs to this exact LB level, not its max-level row.
            if str(dependency['id'])==str(source['id']):
                return [source]
            scopes=('enemy',) if source['kind']=='enemy' else ('skill','lb')
            rows=self.connection.execute('SELECT provenance FROM records WHERE source=? AND source_id=? ORDER BY level DESC',
                (source['source'],str(dependency['id'])))
            candidates=[json.loads(row[0]) for row in rows]
            ordinary=[r for r in candidates if record_scope(r)==scopes[0]]
            return ordinary+[r for r in candidates if r['kind']=='lb'][:1] if 'lb' in scopes else ordinary
        rows = self.connection.execute(
            "SELECT provenance FROM records WHERE source=? AND scope=? AND source_id=? ORDER BY level DESC",
            (source["source"], reference_scope(source, dependency["kind"]), str(dependency["id"])))
        candidates = [json.loads(row[0]) for row in rows]
        # Source LBs intentionally retain every level; an LB reference names
        # the strongest available level of that same revision.
        return candidates[:1] if dependency["kind"] == "lb" else candidates

    def resolve(self, source, dependency):
        candidates = self.candidates(source, dependency)
        if len(candidates) != 1:
            reason = "Missing" if not candidates else "Ambiguous"
            raise ValueError(f"{reason} {dependency['kind']} reference {dependency['id']} in {source['source']}/{reference_scope(source, dependency['kind'])}")
        row = self.connection.execute("SELECT payload FROM records WHERE source_key=?", (candidates[0]["key"],)).fetchone()
        return SourceRecord(**json.loads(row[0]))

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
