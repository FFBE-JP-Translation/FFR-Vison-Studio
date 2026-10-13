"""The review corpus extends the previous reader with ALL JP-client LB levels."""
from pathlib import Path

from tools.ability_converter.sources import ROOT, SourceRecord, iter_sources, master_record, read


def iter_complete_sources():
    # Keep all historical/regional identities; numeric IDs alone are not unique.
    yield from iter_sources(archive=Path('S:/ffbeEquip-master.zip'), all_levels=True)
    folder = ROOT/'build/devui/live_jp'
    parents = {str(v['lb_id']): v for v in read(folder/'F_LIMITBURST_MST.json')['rows']}
    path = folder/'F_LIMITBURST_LV_MST.json'
    for row in read(path)['rows']:
        sid, level = str(row['lb_id']), str(row['level'])
        parent = parents.get(sid)
        if parent is None:
            yield SourceRecord('JP_CLIENT', 'lb', sid, {'name': f'LB {sid}', '_masterLevel': row},
                               str(path), level, ['LB level has no parent master; opcode/target metadata unavailable'])
        else:
            record = master_record({**parent, **row}, 'F_LIMITBURST_MST', path=str(path))
            record.level = level
            record.data['_parentMasterPath'] = str(folder/'F_LIMITBURST_MST.json')
            yield record
