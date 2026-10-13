"""Portable LB dependencies resolved only beside the selected source tables."""
from copy import copy, deepcopy
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path

from .catalog import reference_scope
from .sources import master_record, read, structured_records


@lru_cache(maxsize=6)
def _rows(path, modified, size):
    return read(path)


def rows(path):
    path=Path(path)
    try:
        stat=path.stat()
        return _rows(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
    except OSError as ex:
        raise ValueError(f"Linked LB source table is unavailable: {path.name}") from ex


class FolderResolver:
    def __init__(self, directory, source, *, master=False):
        self.directory=Path(directory);self.source=source;self.master=master

    def resolve(self, source, dependency):
        if source['source']!=self.source or reference_scope(source,dependency['kind'])!='skill':
            raise ValueError('LB dependency must stay in its selected source revision and player-skill namespace')
        sid=str(dependency['id']);candidates=[]
        if self.master:
            for table,key in (('F_ABILITY_MST','ability_id'),('F_MAGIC_MST','magic_id')):
                path=self.directory/(table+'.json')
                # One absent table must not prevent an unambiguous match in the other.
                if not path.is_file():continue
                candidates.extend(master_record(row,table,path=str(path)) for row in rows(path)['rows']
                                  if str(row.get(key))==sid)
        else:
            path=self.directory/'skills.json'
            data=rows(path)
            if sid in data:candidates.extend(structured_records({sid:data[sid]},self.source,'skills',path))
        if len(candidates)!=1:
            raise ValueError(f"{'Missing' if not candidates else 'Ambiguous'} linked LB skill {sid} in {self.source}")
        return candidates[0]


def attach(source, record, resolver):
    """Capture dependencies while preserving all source restrictions on the root."""
    from .commands import RecordingResolver, SNAPSHOT_VERSION
    from .compiler import source_costs
    from .resonance import converter, source_record
    if record.kind!='lb' or record.id!=str(source['lbId']):
        raise ValueError('LB snapshot identity differs from its presentation source')
    # The master reader decodes compound vectors which the older presentation
    # profile keeps as strings. Preserve those canonical mechanics in the save.
    source=deepcopy(source)
    entries=source.get('components') or []
    source['components']=[{**(entries[i] if i<len(entries) else {}),'index':i,
        'range':raw[0],'target':raw[1],'type':raw[2],'params':deepcopy(raw[3])}
        for i,raw in enumerate(record.data['effects_raw'])]
    source['elements']=['Thunder' if e=='Lightning' else e for e in record.data.get('element_inflict') or []]
    source.setdefault('rawLb',{})['cost']=source_costs(record.data)['lb_cost']
    projected=source_record(source)
    root=replace(record,data={**deepcopy(record.data),**projected.data})
    recorded=RecordingResolver(root,resolver)
    compiler=copy(converter());compiler.resolver=recorded
    compiler.convert(root)
    result=deepcopy(source)
    result['conversionSource']={'schemaVersion':SNAPSHOT_VERSION,'root':root.key,
                               'records':[asdict(r) for r in recorded.records.values()]}
    return result
