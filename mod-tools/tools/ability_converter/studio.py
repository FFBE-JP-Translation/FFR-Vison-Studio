"""Read Studio's regional catalog without interpreting display descriptions."""
from copy import deepcopy

from .sources import SourceRecord

REGIONS = {"GL_2022":"GL", "JP_2022":"JP", "GL_2024":"GLW", "JP_2024":"JPW", "JP_CLIENT":"LIVE"}
TABLES = {"ability":"skills_ability", "magic":"skills_magic", "passive":"skills_passive"}


class StudioResolver:
    def __init__(self, catalog=None):
        if catalog is None:
            import ffbe_catalog
            catalog = ffbe_catalog
        self.catalog = catalog

    def record(self, entry, region):
        if entry.get("sourceRecord"):
            record = SourceRecord(**deepcopy(entry["sourceRecord"]))
            if record.id != str(entry["id"]) or record.kind != str(entry["kind"]).lower():
                raise ValueError("Studio ability identity differs from its structured source")
            if region and REGIONS.get(record.source) != region:
                raise ValueError("Studio ability source revision differs from the unit's selected revision")
            return record
        table = TABLES.get(str(entry.get("kind", "")).lower())
        row = self.catalog.sources().get(region, {}).get(table, {}).get(str(entry["id"]))
        if row is None:
            raise ValueError(f"Missing structured source for {region}/{entry.get('kind')}/{entry['id']}")
        return SourceRecord(**self.catalog.skill_record(region, entry["id"], table, row))

    def resolve(self, source, dependency):
        region = REGIONS.get(source["source"])
        if region is None or source["kind"] in ("enemy", "field") or dependency["kind"] in ("lb", "field"):
            raise ValueError("This reference is unavailable in the ordinary Studio skill catalog")
        tables = self.catalog.sources().get(region, {})
        candidates = []
        for table in TABLES.values():
            row = tables.get(table, {}).get(str(dependency["id"]))
            if row is not None:
                candidates.append(SourceRecord(**self.catalog.skill_record(region, dependency["id"], table, row)))
        if len(candidates) != 1:
            raise ValueError(f"{'Missing' if not candidates else 'Ambiguous'} skill reference {dependency['id']} in {source['source']}")
        return candidates[0]
