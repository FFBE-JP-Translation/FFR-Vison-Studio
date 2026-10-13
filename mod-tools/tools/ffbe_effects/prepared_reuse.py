"""Explicit preservation of reviewed prepared groups during offline enrichment.

Retained media is not represented as a fresh canonical conversion. Source
timelines and every shipped byte are checked; missing historical decoder or
export settings stay unknown in the report.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re


def group_key(item):
    return item.get('phase', 'action'), item['anchor'], item['layer']


def rebuild_groups(groups, provenance, spawns, sources):
    """Supersede whole prepared groups containing explicitly selected sources."""
    sources = set(sources or [])
    if any(not isinstance(name,str) or '/' in name or '\\' in name or ':' in name
           or not name.lower().endswith('.bmb') or len(name)<=4 for name in sources):
        raise ValueError('Rebuilt sources must be BMB basenames')
    sources = {name.casefold() for name in sources}
    selected = {group_key(spawn) for spawn in spawns if spawn['file'].casefold() in sources}
    rebuilt = [item for item in provenance['groups'] if group_key(item) in selected]
    provenance = deepcopy(provenance)
    provenance['groups'] = [item for item in provenance['groups'] if group_key(item) not in selected]
    if rebuilt:
        provenance['rebuiltGroups'] = [{**deepcopy(item),
            'requestedSources':sorted({spawn['file'] for spawn in spawns
                if group_key(spawn)==group_key(item) and spawn['file'].casefold() in sources}),
            'policy':'replace complete group using current source decoder and recorded export profile'}
            for item in rebuilt]
    return {key:value for key,value in groups.items() if key not in selected}, provenance


def archive_rebuilt_issues(provenance, issues, spawns):
    """Move exact obsolete source/export warnings beside their superseded art.

    Host limitations remain current. A file shared with retained groups keeps
    its warning too; fresh source audits are added separately by preparation.
    """
    provenance = deepcopy(provenance)
    rebuilt = {group_key(item):item for item in provenance.get('rebuiltGroups',[])}
    files, planes = defaultdict(set), defaultdict(set)
    for spawn in spawns:
        key=group_key(spawn)
        files[spawn['file']].add(key)
        planes[(spawn['anchor'],spawn['layer'])].add(key)
    current=[]
    for issue in issues:
        owners=next((keys for name,keys in files.items() if issue.startswith(name+': ')),set())
        exported=re.fullmatch(r'([^/]+)/([0-9]+): [0-9]+ sprite frames omitted; [0-9]+ oversized sprite frames scaled down',issue)
        if exported:
            owners=planes.get((exported[1],int(exported[2])),set())
        if owners and owners.issubset(rebuilt):
            for key in owners:
                rebuilt[key].setdefault('historicalIssues',[]).append(issue)
        else:
            current.append(issue)
    return provenance,current


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inside(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Retained media path escapes the project')
    return path


def validate(previous, fresh, root, explicit_profile=None):
    """Return exact reusable groups, provenance, and relevant old limitations."""
    if not previous or previous.get('sourceSha256') != fresh['sourceSha256']:
        raise ValueError('Retaining prepared media requires a matching source snapshot fingerprint')
    if previous.get('sounds') != fresh['sounds']:
        raise ValueError('Retaining prepared media requires an unchanged source sound timeline')
    if previous.get('reconstructionProfile') and explicit_profile is None:
        raise ValueError('Retaining profiled media requires an identical explicit profile')
    if explicit_profile is not None and explicit_profile != previous.get('reconstructionProfile'):
        raise ValueError('A changed explicit profile requires fresh conversion instead of retained media')
    if previous.get('opening') != (explicit_profile or {}).get('opening'):
        raise ValueError('Retaining an opening requires its identical explicit profile')
    old_groups, new_groups = defaultdict(list), defaultdict(list)
    for spawn in previous.get('spawns', []): old_groups[group_key(spawn)].append(spawn)
    for spawn in fresh['spawns']: new_groups[group_key(spawn)].append(spawn)
    for key, spawns in old_groups.items():
        if spawns != new_groups.get(key):
            raise ValueError('Retained source group changed or was previously incomplete: ' + str(key))
    groups, evidence = {}, []
    for visual in previous.get('visuals', []):
        key = group_key(visual)
        if key not in old_groups or key in groups:
            raise ValueError('Retained visual must identify one complete, unique source group')
        directory = inside(root, visual['spec'])
        spec = json.loads((directory/'spec.json').read_text(encoding='utf-8'))
        required = {'spec.json', *(page.get('textureFile', 'tex.bgra')
                                   for page in spec.get('cellmaps', [spec]))}
        checksums = visual.get('checksums', {})
        if not required.issubset(checksums):
            raise ValueError('Retained visual requires complete spec and atlas checksums')
        for filename, expected in checksums.items():
            path = inside(directory, filename)
            if not isinstance(expected, str) or len(expected) != 64 or digest(path) != expected:
                raise ValueError('Retained visual content checksum mismatch: ' + filename)
        groups[key] = deepcopy(visual)
        original = next((item for item in previous.get('retainedLegacyVisuals',{}).get('groups',[])
                         if item.get('name')==visual['name'] and item.get('checksums')==checksums),None)
        evidence.append({'phase':key[0], 'anchor':key[1], 'layer':key[2],
                         'name':visual['name'], 'sourceSpawns':len(old_groups[key]),
                         'checksums':deepcopy(checksums),
                         'originalSettings':original['originalSettings'] if original else 'recorded_profile' if previous.get('reconstructionProfile') else 'unknown',
                         'recordedProfile':deepcopy(original.get('recordedProfile') if original else previous.get('reconstructionProfile')),
                         'recordedConversionAudit':deepcopy(spec.get('conversionAudit', {})),
                         'sourceDependencyHashes':'not asserted; existing reviewed media retained explicitly'})
    if not groups:
        raise ValueError('No complete prepared visual groups are available to retain')
    import ffbe_audio_assets
    audio_path = inside(root, previous['audioBank'])
    audio = ffbe_audio_assets.read(audio_path)
    waves = ffbe_audio_assets.waves(audio_path, audio)
    required_cues = {sound['cueId'] for sound in fresh['sounds']}
    if (fresh.get('cast') or {}).get('bank')=='SE': required_cues.add(100)
    if ((explicit_profile or {}).get('opening') or {}).get('chargeFrame') is not None: required_cues.add(647)
    for cue in required_cues:
        recordings = [record for record in audio.get('recordings', []) if record['sourceCueId']==cue]
        if (str(cue) not in audio['cues'] or str(cue) in audio.get('omitted', {}) or not recordings or
                any(record['sourceWaveId'] not in waves for record in recordings)):
            raise ValueError('Retained audio bank has an omitted or missing recording for cue '+str(cue))
    resolved_screen_ids = {spawn.get('groupId') for spawn in fresh['spawns'] if spawn['anchor']=='screen'}
    issues = []
    for issue in previous.get('issues', []):
        gap = re.fullmatch(r'Group ([^:]+): screen overlay awaits an adapter', issue)
        if not gap or gap[1] not in resolved_screen_ids:
            issues.append(issue)
    provenance = {'policy':'explicitly_retain_reviewed_prepared_groups',
                  'sourceSha256':fresh['sourceSha256'], 'sourceTimelineMatches':True,
                  'allPreparedBytesVerified':True, 'freshCanonicalConversion':False,
                  'audioBankSha256':digest(audio_path), 'audioBankOmissions':deepcopy(audio.get('omitted', {})),
                  'groups':evidence}
    return groups, provenance, issues
