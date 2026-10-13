"""Read-only census of catalog membership, source graphs and prepared artifacts.

Source parseability is never reported as successful rendering. The public
helpers read only; CLI output is confined to its explicitly chosen directory.
"""
from collections import Counter
from contextlib import closing
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import zipfile
import zlib

from .source_placement import normalize_effect_placement, normalize_skill_placement

SCHEMA = 'ffbe-effects-catalog-coverage/1'
ROOT = Path(__file__).resolve().parents[2]


def identity(path):
    path = Path(path)
    with path.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    return {'path': str(path.resolve()), 'sha256': digest, 'bytes': path.stat().st_size}


def load_catalog(path):
    """Validate the catalog's actual unit→form ownership, without hardcoded IDs."""
    path = Path(path)
    rows = json.loads(path.read_bytes())
    if isinstance(rows, dict):
        rows = rows.get('units')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Catalog must contain a nonempty unit list')
    units, owners, ids = [], {}, set()
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r'[0-9]+', str(row.get('id', ''))):
            raise ValueError('Catalog contains an invalid unit ID')
        uid = str(row['id'])
        if uid in ids:
            raise ValueError(f'Duplicate catalog unit {uid}')
        ids.add(uid)
        forms = row.get('forms')
        if not isinstance(forms, list) or not forms:
            raise ValueError(f'{uid}: missing forms')
        forms = [str(form) for form in forms]
        for form in forms:
            if not re.fullmatch(r'[0-9]+', form):
                raise ValueError(f'{uid}: invalid form ID')
            if form in owners:
                raise ValueError(f'{form}: duplicate form owner {owners[form]} / {uid}')
            owners[form] = uid
        units.append({'id': uid, 'name': row.get('name'), 'forms': forms})
    return {'identity': identity(path), 'units': units, 'forms': sorted(owners), 'owners': owners}


def _key(record):
    key = f"{record['source']}/{record['kind']}/{record['id']}"
    return key + '/level/' + str(record['level']) if record.get('level') is not None else key


def _json_blob(blob):
    return json.loads(zlib.decompress(blob))


def _items(value):
    return [item.split(':') for item in re.split('[&,@]', value or '') if item]


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _percentage(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'percent': round(numerator * 100 / denominator, 4) if denominator else None}


class SourceTables:
    """Exact raw GL tables plus the same cached JP tables used by preparation."""
    def __init__(self, root, gl_raw, field_names):
        self.tables, self.identities, self.errors = {}, {}, []
        names = json.loads(Path(field_names).read_bytes())
        self.identities['fieldNames'] = identity(field_names)
        ids = {'F_ABILITY_MST': 'ability_id', 'F_MAGIC_MST': 'magic_id',
               'F_LIMITBURST_MST': 'lb_id', 'F_EFFECT_GROUP_MST': 'qIy86WvJ',
               'F_EFFECT_MST': 'h5t4yBm2'}
        keep = {'effect_frames', '1fVZ3rKd', 'I1B7wNWc', '2HjxCGo6', 'avX1k34K',
                'MotioinType', 'move_type', 'wait'}
        for source in ('GL_2024', 'JP_CLIENT'):
            for table, ident in ids.items():
                path = (Path(gl_raw) / (table + '.txt') if source == 'GL_2024'
                        else root / 'build/devui/live_jp' / (table + '.json'))
                try:
                    if source == 'GL_2024':
                        with path.open(encoding='utf-8') as handle:
                            rows = [{names.get(k, k): v for k, v in json.loads(line).items()}
                                    for line in handle if line.strip()]
                    else:
                        rows = json.loads(path.read_bytes())['rows']
                    self.tables[source, table] = {str(row[ident]): {k: row[k] for k in keep if k in row}
                                                  for row in rows}
                    self.identities[f'{source}/{table}'] = identity(path)
                except (OSError, ValueError, KeyError) as error:
                    self.errors.append(f'{source}/{table}: {error}')
                    self.tables[source, table] = {}

    def table(self, source, name):
        return self.tables.get((source, name), {})


def inspect_source_graph(record, tables):
    """Resolve a source record without simulating particles or dropping bad groups."""
    source, kind, ident = record['source'], record['kind'], str(record['id'])
    table_name = {'ability': 'F_ABILITY_MST', 'magic': 'F_MAGIC_MST', 'lb': 'F_LIMITBURST_MST'}.get(kind)
    issues, groups, files, cues, effect_types = [], [], set(), set(), Counter()
    if table_name is None:
        return {'sourceKey': _key(record), 'resolved': False, 'issues': ['No active presentation table for kind '+kind],
                'groups': [], 'files': [], 'cues': [], 'effectTypes': {}, 'semanticPlacement': False,
                'legacyPlacement': False, 'bmbFormatOnly': False, 'jpPipelineFrameCompatible': False}
    row = record.get('data', {}).get('_master') or tables.table(source, table_name).get(ident)
    if not row:
        return {'sourceKey': _key(record), 'resolved': False, 'issues': ['Missing source presentation row'],
                'groups': [], 'files': [], 'cues': [], 'effectTypes': {}, 'semanticPlacement': False,
                'legacyPlacement': False, 'bmbFormatOnly': False, 'jpPipelineFrameCompatible': False}
    text = row.get('effect_frames') or ''
    semantic, legacy, formats, resolved = True, True, True, True
    for component, component_text in enumerate(text.split('@')):
        for fields in _items(component_text):
            if len(fields) < 3:
                issues.append('Malformed skill group: '+':'.join(fields)); resolved = semantic = legacy = False
                continue
            gid, flags = fields[1], fields[2:]
            placement = normalize_skill_placement(flags)
            semantic &= placement['supported']
            legacy &= (placement['supported'] and len(flags) == 3 and flags[2] == '0'
                       and placement.get('anchorValue') in (1, 2, 3, 4))
            group = tables.table(source, 'F_EFFECT_GROUP_MST').get(gid)
            if group is None and gid == '99999999':
                continue  # Explicit empty effect-group sentinel in source tables.
            if group is None:
                issues.append('Missing effect group '+gid); resolved = False
                continue
            effects = []
            for raw_effect in _items(group.get('effect_frames')):
                normalized = normalize_effect_placement(raw_effect)
                semantic &= normalized['supported']
                eid = raw_effect[1] if len(raw_effect) > 1 else ''
                effect = tables.table(source, 'F_EFFECT_MST').get(eid)
                if effect is None:
                    issues.append('Missing effect definition '+eid); resolved = formats = False
                    effects.append({'raw': raw_effect, 'id': eid, 'missing': True}); continue
                typ = str(effect.get('I1B7wNWc', 'unknown'))
                effect_types[typ] += 1
                payload = effect.get('2HjxCGo6') or ''
                if typ == '5':
                    file = payload.split(':')[0]
                    if file: files.add(file)
                    else: resolved = False; issues.append('Empty particle filename '+eid)
                elif typ == '1':
                    files.update(name for name in payload.split(':') if name)
                    formats = False
                elif typ != '10':
                    formats = False
                effects.append({'raw': raw_effect, 'id': eid, 'type': typ, 'payload': payload,
                                'scale': effect.get('avX1k34K'), 'placementSupported': normalized['supported']})
                if len(raw_effect) > 2 and raw_effect[2] not in ('', '0'):
                    alternate = tables.table(source, 'F_EFFECT_MST').get(raw_effect[2])
                    if alternate is None:
                        issues.append('Missing reverse effect definition '+raw_effect[2]); resolved = False
                    elif str(alternate.get('I1B7wNWc')) != '10':
                        alternate_payload = alternate.get('2HjxCGo6') or ''
                        files.update(alternate_payload.split(':')[:1])
                        if str(alternate.get('I1B7wNWc')) != '5': formats = False
            for sound in _items(group.get('1fVZ3rKd')):
                try: cues.add(int(sound[1]))
                except (ValueError, IndexError): issues.append('Malformed sound cue '+':'.join(sound)); resolved = False
            group_hash = _hash({'effects': effects, 'sounds': group.get('1fVZ3rKd') or ''})
            groups.append({'groupId': gid, 'frame': fields[0], 'component': component,
                           'flags': flags, 'anchor': placement.get('anchorValue'),
                           'placementSupported': placement['supported'], 'definitionSha256': group_hash,
                           'effectCount': len(effects), 'effects': effects,
                           'soundFields': group.get('1fVZ3rKd') or ''})
    jp_row = tables.table('JP_CLIENT', table_name).get(ident)
    expected = record.get('data', {}).get('effect_frames', [])
    expected = [v for group in expected for v in group] if isinstance(expected, list) and all(isinstance(g, list) for g in expected) else None
    try:
        jp_frames = [int(fields[0]) for fields in _items((jp_row or {}).get('effect_frames'))]
        frame_compatible = bool(jp_row) and expected == jp_frames
    except ValueError:
        frame_compatible = False
    return {'sourceKey': _key(record), 'resolved': resolved, 'issues': issues, 'groups': groups,
            'files': sorted(files), 'cues': sorted(cues), 'effectTypes': dict(effect_types),
            'semanticPlacement': semantic, 'legacyPlacement': legacy, 'bmbFormatOnly': formats,
            'jpPipelineFrameCompatible': frame_compatible,
            'graphSha256': _hash(groups), 'sourceEffectFrames': text,
            'hasExplicitEffects': any(group['effectCount'] for group in groups)}


def inspect_particle_files(directory, filenames, *, progress=None):
    """Structural parsing only; texture/mesh existence is not rendered fidelity."""
    from . import ibmb
    directory = Path(directory)
    available = {p.name.casefold(): p for p in directory.iterdir() if p.is_file()}
    records = {}
    for index, filename in enumerate(sorted(set(filenames))):
        if progress and index % 250 == 0:
            progress(f'Inspecting source assets {index}/{len(filenames)}')
        path = available.get(filename.casefold())
        row = {'filename': filename, 'existsInEffectPool': path is not None,
               'format': Path(filename).suffix.lower(), 'parsed': False,
               'dependenciesComplete': False, 'issues': []}
        if path is None:
            row['issues'].append('Not present in the configured effect pool')
        elif row['format'] != '.bmb':
            row['issues'].append('Outside the current BMB particle parser')
        else:
            try:
                effect = ibmb.parse(str(path))
                textures = [name if Path(name).suffix else name+'.png' for name in effect.textures]
                meshes = [name if Path(name).suffix else name+'.m3r' for name in effect.models]
                missing = [name for name in textures+meshes if name.casefold() not in available]
                row.update(parsed=True, dependenciesComplete=not missing,
                           textures=textures, meshes=meshes, missingDependencies=missing,
                           durationFrames=effect.duration, objectCount=len(effect.chunks),
                           bytes=path.stat().st_size,
                           translationModes=sorted({str(c.translation_mode) for c in effect.chunks if c.enabled}),
                           rotationModes=sorted({str(c.rotation_mode) for c in effect.chunks if c.enabled}),
                           scaleModes=sorted({str(c.scale_mode) for c in effect.chunks if c.enabled}),
                           hasMeshes=bool(meshes))
                row['durationKind'] = 'unbounded_sentinel' if effect.duration == 0xffffffff else 'declared_frames'
                if meshes: row['issues'].append('Mesh emitters require fidelity validation; current bake projects them to sprites')
                if missing: row['issues'].append('Missing source texture or mesh dependencies')
            except Exception as error:
                row['issues'].append(type(error).__name__+': '+str(error))
        records[filename] = row
    return records


def inspect_prepared(root):
    """Inspect existing manifests/spec files; no native visual acceptance inferred."""
    forms, assets = {}, {}
    for path in sorted((root/'data/ffbe/presentation').glob('*.json')):
        doc = json.loads(path.read_bytes())
        if not isinstance(doc.get('moves'), dict): continue
        moves = {}
        for key, move in doc['moves'].items():
            missing, projects = [], []
            for visual in move.get('visuals', []):
                spec = visual.get('spec')
                if not isinstance(spec, str): missing.append('missing spec reference'); continue
                spec_path = root/spec/'spec.json'
                if spec not in assets:
                    good, pages = spec_path.is_file(), []
                    if good:
                        spec_doc = json.loads(spec_path.read_bytes())
                        for index, page in enumerate(spec_doc.get('cellmaps', [spec_doc])):
                            filename = page.get('textureFile', 'tex'+(f'_{index}' if index else '')+'.bgra')
                            pages.append(spec_path.parent/filename)
                        good = bool(pages) and all(p.is_file() for p in pages)
                    assets[spec] = {'present': good, 'pageCount': len(pages)}
                projects.append(spec)
                if not assets[spec]['present']: missing.append(spec)
            moves[key] = {'visualProjects': len(projects), 'preparedFilesPresent': bool(projects) and not missing,
                          'missing': missing,
                          'declaredVisualCoverageComplete': move.get('visualCoverage', {}).get('complete') is True,
                          'declaredVisualOmissions': len(move.get('visualCoverage', {}).get('omitted', [])),
                          'sourceOffsetsApplied': move.get('sourcePlacement', {}).get('applied') is True,
                          'sourceSha256': move.get('sourceSha256'),
                          'soundOmissions': len(move.get('soundOmissions', {})),
                          'visualAcceptance': 'not inferred from file presence'}
        forms[str(doc.get('form', path.stem))] = {'manifest': identity(path), 'moves': moves}
    return {'forms': forms, 'assets': assets}


def inspect_unit_archives(unit_dir, forms):
    records = {}
    for form in forms:
        path = Path(unit_dir)/(form+'.ffr')
        row = {'path': str(path.resolve()), 'exists': path.is_file(), 'metadataReadable': False,
               'preparedEffectsEmbedded': False, 'preparedMoveKeys': []}
        if path.is_file():
            row['bytes'] = path.stat().st_size
            try:
                with zipfile.ZipFile(path) as archive:
                    names = set(archive.namelist())
                    row['metadataReadable'] = f'native_kits/{form}.json' in names
                    marker = f'presentation/effects/{form}.json'
                    if marker in names:
                        if archive.getinfo(marker).file_size > 16*1024*1024:
                            raise ValueError('Effects metadata exceeds the bounded census limit')
                        manifest = json.loads(archive.read(marker))
                        row['preparedEffectsEmbedded'] = manifest.get('form') == form
                        row['preparedMoveKeys'] = list(manifest.get('moves', {}))
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                row['error'] = str(error)
        records[form] = row
    return {'directory': str(Path(unit_dir).resolve()), 'verification': 'ZIP central directory and metadata only; payload hashes not verified',
            'forms': records}


def inspect_audio(path, cue_ids):
    from .acb_cues import CueGraph, utf
    path = Path(path)
    if not path.is_file():
        return {'path': str(path), 'error': 'Missing SE bank', 'cues': {}}
    data = path.read_bytes()
    header = utf(data)[1][0]
    graph = CueGraph(header)
    rows = {row['CueId']: row for row in utf(header['CueTable'])[1]}
    results = {}
    for cue_id in sorted(cue_ids):
        result = {'present': cue_id in rows, 'nativeCueGraphCompatible': False, 'issues': []}
        try:
            row = rows[cue_id]
            alternatives = graph.alternatives(row)
            waves = [graph.row('WaveformTable', index) for index in alternatives]
            if not waves: raise ValueError('Cue graph contains no supported waveforms')
            if any(wave['Streaming'] or wave['EncodeType'] not in (2, 6)
                   or wave['ExtensionData'] != 65535 for wave in waves):
                raise ValueError('Cue requires unsupported external/non-HCA/loop metadata')
            result.update(nativeCueGraphCompatible=True, waveformIndices=alternatives,
                          channelCounts=sorted({wave['NumChannels'] for wave in waves}),
                          durationMs=row.get('Length'))
        except (ValueError, KeyError, IndexError) as error:
            result['issues'].append(str(error))
        results[str(cue_id)] = result
    return {'source': identity(path), 'verification': 'ACB cue graph and wave metadata only; no sound decoded or audible acceptance inferred',
            'cues': results}


def build_census(root=ROOT, *, catalog_path=None, unit_dir=None,
                 gl_raw_dir=Path('T:/Projects/ffbe/ffbe-wiki-tools/datamine/dat_raw/gl'),
                 field_names_path=Path('T:/ffbe_patch/keys/field_names.json'),
                 particle_dir=None, audio_path=None, parse_particles=True, progress=None):
    """Read the complete catalog and retained source libraries, without rendering.

    All non-passive memberships are reported, including mechanically held
    entries. Current conversion eligibility is a separate, narrower count.
    Dependency snapshots are counted separately from root move memberships.
    No count is a measure of the user's visual-accuracy target.
    """
    root = Path(root)
    catalog = load_catalog(catalog_path or root/'build/devui/ffbe_index.json')
    unit_dir = Path(unit_dir or root/'build/native-editor/host/ffbe/units')
    tables = SourceTables(root, gl_raw_dir, field_names_path)
    prepared = inspect_prepared(root)
    db_path = root/'data/ability_converter/vision-kits.sqlite'
    forms, membership_counts, roots, graphs, definitions = {}, Counter(), {}, {}, {}
    with closing(sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro', uri=True)) as database:
        for form, owner, blob in database.execute('SELECT form,unit_id,payload FROM kits'):
            if form not in catalog['owners']: continue
            kit = _json_blob(blob)
            entries = []
            for entry in kit.get('entries', []):
                membership_counts[entry['kind']+'/'+entry['status']] += 1
                if entry['kind'] == 'PASSIVE': continue
                key = entry['sourceKey']
                entries.append({'sourceKey': key, 'kind': entry['kind'], 'status': entry['status']})
                info = roots.setdefault(key, {'forms': [], 'readyForms': [], 'records': [], 'profilePresent': False})
                info['forms'].append(form)
                if entry['status'] == 'ready': info['readyForms'].append(form)
            forms[form] = {'unitId': catalog['owners'][form], 'kitOwner': owner,
                           'membershipOwnerMatches': str(owner) == catalog['owners'][form], 'activeEntries': entries}
        for index, (key, supported, blob) in enumerate(database.execute('SELECT source_key,supported,payload FROM profiles')):
            if key not in roots: continue
            if progress and index % 2000 == 0: progress(f'Reading source profiles {index}')
            profile = _json_blob(blob)
            root_info = roots[key]
            root_info['profilePresent'] = True
            root_info['mechanicsAvailable'] = bool(supported)
            snapshot = profile.get('snapshot', {})
            records = [record for record in snapshot.get('records', [])
                       if record.get('kind') in ('ability', 'magic', 'lb')]
            if not records and key.split('/')[1] not in ('ability', 'magic', 'lb'):
                root_info['issues'] = ['Non-particle source kind '+key.split('/')[1]]
            for record in records:
                record_key = _key(record)
                root_info['records'].append(record_key)
                if record_key in graphs: continue
                graph = inspect_source_graph(record, tables)
                for group in graph['groups']:
                    definition = group['definitionSha256']
                    definitions.setdefault(definition, {'effects': group.pop('effects'),
                                                        'soundFields': group.pop('soundFields')})
                    group.pop('effects', None); group.pop('soundFields', None)
                graphs[record_key] = graph
            # Exact source fingerprint used by the prepared manifest contract.
            records_for_hash = [{k: record.get(k) for k in ('source', 'kind', 'id', 'level', 'data')}
                                for record in snapshot.get('records', [])]
            source_sha = hashlib.sha256(json.dumps(records_for_hash, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            root_info['sourceSha256'] = source_sha
    referenced_files = {filename for graph in graphs.values() for filename in graph['files'] if filename}
    if progress: progress(f'Referenced {len(referenced_files)} distinct source files; inspecting dependencies')
    assets = (inspect_particle_files(particle_dir or root/'build/ffbe_cpk/effects_dec', referenced_files, progress=progress)
              if parse_particles else {})
    all_cues = {cue for graph in graphs.values() for cue in graph['cues']}
    # Native opening cues are outside the per-skill effect_frames list.
    if any('/ability/' in key for key in roots): all_cues.add(100)
    if any('/lb/' in key for key in roots): all_cues.add(647)
    audio = inspect_audio(audio_path or root/'data/ffbe/audio/SE.acb', all_cues)
    if 'error' in audio and audio_path is None:
        audio = inspect_audio(Path('S:/FFBE JP Data Export/public/SE.acb'), all_cues)
    for info in roots.values():
        records = [graphs[key] for key in info['records']]
        info['sourceResolved'] = bool(records) and all(g['resolved'] for g in records)
        info['placementSemanticsResolved'] = bool(records) and all(g['semanticPlacement'] for g in records)
        info['legacyPlacementEligible'] = bool(records) and all(g['legacyPlacement'] for g in records)
        info['jpPipelineFramesEligible'] = bool(records) and all(g['jpPipelineFrameCompatible'] for g in records)
        info['bmbFormatOnly'] = bool(records) and all(g['bmbFormatOnly'] for g in records)
        own_files = {filename for g in records for filename in g['files']}
        info['explicitVisuals'] = any(g.get('hasExplicitEffects') for g in records)
        info['particleDependenciesPresent'] = (all(assets.get(f, {}).get('dependenciesComplete') for f in own_files)
                                                if parse_particles else None)
        info['structuralPreparationCandidate'] = (info['sourceResolved'] and info['legacyPlacementEligible']
                                                  and info['jpPipelineFramesEligible'] and info['bmbFormatOnly']
                                                  and info['particleDependenciesPresent'] is True)
        info['visualAccuracy'] = 'unmeasured'
    archive_info = inspect_unit_archives(unit_dir, catalog['forms'])
    supplemental_dir = root/'build/ffbe-effects-delivery'
    supplemental_forms = [p.stem for p in supplemental_dir.glob('*.ffr') if p.stem in catalog['owners']]
    supplemental = inspect_unit_archives(supplemental_dir, supplemental_forms)
    prepared_present, prepared_current, prepared_complete, applied = set(), set(), set(), set()
    for form, info in prepared['forms'].items():
        for key, move in info['moves'].items():
            pair = (form, key)
            if move['preparedFilesPresent']: prepared_present.add(pair)
            if move['preparedFilesPresent'] and move['sourceSha256'] == roots.get(key, {}).get('sourceSha256'):
                prepared_current.add(pair)
                if move['declaredVisualCoverageComplete']: prepared_complete.add(pair)
                if move['sourceOffsetsApplied']: applied.add(pair)
    all_active = [(form, entry) for form, f in forms.items() for entry in f['activeEntries']]
    ready = [(form, entry) for form, entry in all_active if entry['status'] == 'ready']
    memberships = {'allActive': len(all_active), 'readyActive': len(ready), 'byKindAndStatus': dict(membership_counts)}
    sources = {}
    for label in ('sourceResolved', 'placementSemanticsResolved', 'legacyPlacementEligible',
                  'jpPipelineFramesEligible', 'bmbFormatOnly', 'particleDependenciesPresent', 'structuralPreparationCandidate'):
        sources[label] = {'distinctMoves': _percentage(sum(info[label] is True for info in roots.values()), len(roots)),
                          'readyMemberships': _percentage(sum(roots[e['sourceKey']][label] is True for _, e in ready), len(ready))}
    anchors = Counter(str(group['anchor']) for graph in graphs.values() for group in graph['groups'])
    types = Counter()
    for graph in graphs.values(): types.update(graph['effectTypes'])
    for form, info in forms.items():
        ready_keys = {e['sourceKey'] for e in info['activeEntries'] if e['status'] == 'ready'}
        info['readyActiveCount'] = len(ready_keys)
        info['preparedReadyMoves'] = sum((form, key) in prepared_current for key in ready_keys)
        info['allReadyMovesPrepared'] = bool(ready_keys) and info['preparedReadyMoves'] == len(ready_keys)
        info['unitArchivePresent'] = archive_info['forms'][form]['exists']
    output = {'schema': SCHEMA, 'catalog': catalog, 'kitDatabase': identity(db_path),
              'sourceInputs': tables.identities, 'sourceInputErrors': tables.errors,
              'counts': {'catalogUnits': len(catalog['units']), 'catalogForms': len(catalog['forms']),
                         'formsWithKits': len(forms), 'missingKits': sorted(set(catalog['forms'])-set(forms)),
                         'distinctActiveMoves': len(roots), 'distinctActiveDependencyRecords': len(graphs),
                         'distinctMoveEffectGraphs': len({g['graphSha256'] for g in graphs.values() if 'graphSha256' in g}),
                         'distinctGroupDefinitions': len(definitions), 'distinctSourceFiles': len(referenced_files),
                         'distinctBmbFiles': sum(Path(f).suffix.lower()=='.bmb' for f in referenced_files),
                         'distinctTextureDependencies': len({t for a in assets.values() for t in a.get('textures', [])}),
                         'distinctMeshDependencies': len({t for a in assets.values() for t in a.get('meshes', [])}),
                         'referencedSoundCueIds': len(all_cues), 'anchorOccurrences': dict(anchors), 'effectTypeOccurrences': dict(types)},
              'memberships': memberships, 'sourceCoverage': sources,
              'renderedCoverage': {'preparedManifestForms': len(prepared['forms']),
                                   'preparedMoveMemberships': len(prepared_present),
                                   'currentSourcePreparedMoveMemberships': len(prepared_current),
                                   'currentSourceDeclaredCompleteMemberships': len(prepared_complete),
                                   'sourceOffsetAppliedMemberships': len(applied),
                                   'nativeVisualAccuracy': 'unmeasured by this census',
                                   'accuracyTarget': '80% is visual fidelity, not a source or bundle count threshold'},
              'bundleCoverage': {'rawUnitArchivePresence': _percentage(sum(r['exists'] for r in archive_info['forms'].values()), len(catalog['forms'])),
                                 'catalogArchivesWithPreparedEffects': sum(r['preparedEffectsEmbedded'] for r in archive_info['forms'].values()),
                                 'supplementalArchivesWithPreparedEffects': sum(r['preparedEffectsEmbedded'] for r in supplemental['forms'].values())},
              'limitations': ['Source graph parsing is not rendering or visual acceptance.',
                              'Dependency snapshots include linked source records before final component filtering; they are reported separately from root memberships.',
                              'Empty explicit source graphs are not counted as proof of a rendered effect.',
                              'Structural candidates may still fail actual particle/audio conversion or require approximations.',
                              'Current pipeline candidates compare the existing JP source start-frame gate; requested-region graph resolution is separate.',
                              'Host rectangle, movement and view projection fidelity require native/source comparisons.',
                              'Archive census verifies central directory/metadata, not all payload hashes.'],
              'forms': forms, 'moves': roots, 'sourceGraphs': graphs, 'groupDefinitions': definitions,
              'assets': assets, 'audio': audio, 'prepared': prepared,
              'unitArchives': archive_info, 'supplementalUnitArchives': supplemental}
    return output


def write_summary(report, path):
    """Write a short human-readable census without turning counts into fidelity."""
    counts = report['counts']
    assets = report['assets']
    audio = report['audio'].get('cues', {})
    sentinel = sorted(name for name, item in assets.items() if item.get('durationFrames') == 0xffffffff)
    missing = [name for name, item in assets.items() if not item['existsInEffectPool']]
    rendered, bundled = report['renderedCoverage'], report['bundleCoverage']
    lines = ['# Vision effects catalog census', '',
             'This report measures catalog and source completeness. **It does not measure visual accuracy.** '
             'The requested 80% target concerns resemblance to the source, allowing approximations; it is not a success-rate threshold.', '',
             '## Scope and existing packages', '',
             f"- Catalog: **{counts['catalogUnits']:,} visions / {counts['catalogForms']:,} forms**, read from `{report['catalog']['identity']['path']}`.",
             f"- Forms with source kits: **{counts['formsWithKits']:,}**; missing kits: **{len(counts['missingKits'])}**.",
             f"- Active/held memberships: **{report['memberships']['allActive']:,}**; mechanically ready active memberships: **{report['memberships']['readyActive']:,}**.",
             f"- Distinct active/held root move identities: **{counts['distinctActiveMoves']:,}**. Passives remain separately accounted in the JSON.",
             f"- Existing base `.ffr` archives: **{bundled['rawUnitArchivePresence']['numerator']:,}/{counts['catalogForms']:,}**, under `{report['unitArchives']['directory']}`.",
             f"- Main catalog archives containing prepared particle packs: **{bundled['catalogArchivesWithPreparedEffects']}**. Supplemental reviewed archives: **{bundled['supplementalArchivesWithPreparedEffects']}**.", '',
             '## Distinct source workload', '',
             '| Item | Count |', '| --- | ---: |',
             f"| Linked active source records | {counts['distinctActiveDependencyRecords']:,} |",
             f"| Distinct move effect graphs | {counts['distinctMoveEffectGraphs']:,} |",
             f"| Distinct effect-group definitions | {counts['distinctGroupDefinitions']:,} |",
             f"| Referenced BMB files | {counts['distinctBmbFiles']:,} |",
             f"| Other referenced files | {counts['distinctSourceFiles']-counts['distinctBmbFiles']:,} |",
             f"| Source BMB files present and structurally parsed | {sum(a['parsed'] for a in assets.values()):,} |",
             f"| Texture dependencies of parsed BMBs | {counts['distinctTextureDependencies']:,} |",
             f"| Mesh dependencies of parsed BMBs | {counts['distinctMeshDependencies']:,} |",
             f"| Parsed BMBs referencing mesh resources | {sum(a.get('hasMeshes', False) for a in assets.values()):,} |",
             f"| Referenced source sound cue IDs | {counts['referencedSoundCueIds']:,} |",
             f"| Referenced cues present in SE bank | {sum(c['present'] for c in audio.values()):,} |",
             f"| Cues compatible with current native cue-graph parser | {sum(c['nativeCueGraphCompatible'] for c in audio.values()):,} |", '',
             'These are reusable source assets, not separate bakes for each form membership. '
             'BMB structural parse success does not establish particle simulation or mesh projection fidelity.', '',
             '## Source interpretation and current preparation gate', '',
             '| Test | Distinct root moves | Ready memberships |', '| --- | ---: | ---: |']
    for key, value in report['sourceCoverage'].items():
        a, b = value['distinctMoves'], value['readyMemberships']
        lines.append(f"| {key} | {a['numerator']:,}/{a['denominator']:,} ({a['percent']}%) | {b['numerator']:,}/{b['denominator']:,} ({b['percent']}%) |")
    lines += ['', 'The JP frame-gate columns describe the historical JP-only reader. '
              'A matching-region catalog reader has now been implemented, but that change alone does not mean the source has been rendered. '
              'Exact timing comparisons and unsupported-format reports must remain in the production conversion.', '',
              '## Existing rendered assets', '',
              f"Prepared project files exist for **{rendered['preparedMoveMemberships']} move/form memberships** across **{rendered['preparedManifestForms']} form manifests**. "
              f"Of those, **{rendered['currentSourcePreparedMoveMemberships']}** match current source snapshot hashes, and "
              f"**{rendered['currentSourceDeclaredCompleteMemberships']}** declare no source visual omissions. "
              f"**{rendered['sourceOffsetAppliedMemberships']}** record the newly recovered source rectangle/offset contract as applied.", '',
              'These are file/metadata findings. Visual accuracy remains unmeasured by this census. '
              'A manifest declaration is not independent native visual acceptance.', '',
              '## Concrete gaps', '',
              f"- **{len(missing):,}** referenced files are absent from the configured effect pool; this includes **{sum(Path(name).suffix.lower()=='.bmb' for name in missing):,} BMBs**. "
              'CGG/CGS files outside that pool are distinguished from BMB parser failures.',
              f"- **{len(sentinel)}** referenced BMBs declare `0xffffffff` duration. This is an unbounded sentinel; a batch must use a finite owning-action lifetime instead of baking billions of frames.",
              '- Screen projection, source unit movement, mesh projection and particle variation need source/native comparison. No camera change is implied by the census.',
              '- Audio cue graph compatibility does not establish successful codec conversion or audible timing.',
              '- ZIP metadata was inspected, but this census does not verify every archive payload hash.', '',
              'The machine-readable JSON retains every form, move, graph, group definition, asset dependency, omission and source-file SHA-256. '
              'It is the authoritative detailed census for this run.', '', 'Unbounded-duration source files:', '']
    lines += ['- `'+name+'`' for name in sentinel] or ['- None observed.']
    Path(path).write_text('\n'.join(lines)+'\n', encoding='utf-8')


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--unit-dir', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_census(args.root, catalog_path=args.catalog, unit_dir=args.unit_dir,
                          progress=lambda message: print(message, flush=True))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, separators=(',', ':'))+'\n', encoding='utf-8')
    write_summary(report, args.out.with_suffix('.md'))
    print(json.dumps({key:report[key] for key in ('counts', 'memberships', 'sourceCoverage', 'renderedCoverage', 'bundleCoverage')}, indent=2))


if __name__ == '__main__':
    main()
