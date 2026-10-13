"""Offline publisher: unchanged prepared artwork, one copy of each payload."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import zlib
import ffbe_effect_bundle as old
import ffbe_effect_refs as refs
from .conversion_io import file_lock


def recover_raw_spec(payload, expected):
    """Reverse a legacy in-place portable import only if the original SHA matches.

    Older Studio imports shared project names with the offline exporter. The
    sorted portable JSON can replace its raw spec. Restore exporter ordering and
    texture metadata in memory; never accept merely similar geometry.
    """
    spec = old._json(payload)
    if spec.get('textureEncoding') != 'zlib': return None
    def ordered(value, keys):
        return {**{k: value[k] for k in keys if k in value}, **{k: v for k,v in value.items() if k not in keys}}
    for page in spec.get('cellmaps', []):
        for key in ('textureEncoding','textureBytes','textureSha256'): page.pop(key, None)
        if page.get('textureFile', '').endswith('.z'): page['textureFile'] = page['textureFile'][:-2]
    for key in ('textureEncoding','textureBytes','textureSha256','textureFile'): spec.pop(key, None)
    for page in [spec, *spec.get('cellmaps', [])]:
        page['cells'] = [ordered(c, ['name','pos','size','pivot']) for c in page.get('cells', [])]
    spec['model']['parts'] = [ordered(p, ['name','parent','type','blend','inherit']) for p in spec['model']['parts']]
    animations = []
    for animation in spec['animations']:
        attrs = ['Cell','Posz','Sclx','Scly','Hide','PartsColor'] if animation.get('isSetup') else ['Cell','Posx','Posy','Sclx','Scly','Rotz','Alpha','Hide','Fliph','Flipv','Posz']
        source = animation['parts']
        parts = {}
        for p in spec['model']['parts']:
            name = p['name']
            if name in source:
                parts[name] = ordered(source[name], ['Hide','Sclx','Scly','Posx'] if name == 'root' else attrs)
                for frame in parts[name].get('PartsColor', []):
                    frame[1] = ordered(frame[1], ['target','blendType','rgba','rate'])
        parts.update({k: v for k,v in source.items() if k not in parts})
        animation['parts'] = parts
        animations.append(ordered(animation, ['name','sortMode','fps','frameCount','canvas','pivot','isSetup','parts']))
    spec['animations'] = animations
    if 'conversionAudit' in spec:
        spec['conversionAudit'] = ordered(spec['conversionAudit'], ['droppedSpriteFrames','shrunkSpriteFrames','maxCellSize','sourceSpriteFrames','atlasPages','atlasBytes'])
    if 'cellmaps' in spec:
        spec['cellmaps'] = [ordered(p, ['cellmapName','pixelSize','cells','imagePath','textureFile']) for p in spec['cellmaps']]
    spec = ordered(spec, ['pixelSize','cells','model','animations','cellmapName','animePackName','imagePath','conversionAudit','cellmaps','runtimeScale'])
    for formatting in ({'indent': 1}, {'ensure_ascii': False, 'separators': (',', ':')}):
        restored = json.dumps(spec, **formatting).encode('utf-8')
        if old._sha(restored) == expected: return restored
    return None


class Publisher:
    def __init__(self, root, delivery, compression_cache=None):
        self.root, self.delivery = Path(root), Path(delivery)
        self.compression_cache = Path(compression_cache) if compression_cache else None
        self.projects, self.banks, self.validated = {}, {}, set()

    def source(self, name, expected=None):
        path = old._disk(self.root / 'data/ffbe', name)
        if path.stat().st_size > refs.MAX_FILE:
            raise ValueError('Prepared file exceeds the individual file budget: ' + name)
        raw = path.read_bytes()
        if expected and old._sha(raw) != expected:
            restored = recover_raw_spec(raw, expected) if name.endswith('/spec.json') else None
            if restored is None: raise ValueError('Prepared dependency changed: ' + name)
            raw = restored
        return raw

    def put(self, raw, *, compress=False, link=None):
        if len(raw) > refs.MAX_FILE:
            raise ValueError('Shared file exceeds its decoded budget')
        payload = zlib.compress(raw, 9) if compress else raw
        info = {'sha256': old._sha(payload), 'size': len(payload), 'encoding': 'zlib' if compress else 'raw',
                'decodedSha256': old._sha(raw), 'decodedSize': len(raw)}
        refs.descriptor(info)
        target = self.delivery / refs.blob_name(info['sha256'])
        if info['sha256'] not in self.validated:
            with file_lock(target.with_suffix('.lock')):
                valid = target.is_file() and target.stat().st_size == len(payload)
                if valid:
                    with target.open('rb') as stream:
                        valid = hashlib.file_digest(stream, 'sha256').hexdigest() == info['sha256']
                if not valid:
                    # Reuse the existing lossless compression cache physically,
                    # not just logically. Fallback works across disk volumes.
                    if link and not target.exists():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        try: os.link(link, target)
                        except OSError: refs.atomic(target, payload)
                    else:
                        refs.atomic(target, payload)
            self.validated.add(info['sha256'])
        return info

    def texture(self, page, expected, source_dir, name):
        identity = old._sha(old.encoded({'page': {k: page.get(k) for k in
            ('pixelSize', 'textureEncoding', 'textureBytes', 'textureSha256')}, 'sha256': expected}))
        receipt = self.delivery / 'work/textures' / (identity + '.json')
        with file_lock(receipt.with_suffix('.lock')):
            if receipt.is_file():
                cached = json.loads(receipt.read_bytes())
                target = self.delivery / refs.blob_name(cached['file']['sha256'])
                if target.is_file():
                    stat = target.stat()
                    if cached.get('blobStat') == [stat.st_size, stat.st_mtime_ns]:
                        return cached
            compressed_path = self.compression_cache / ('zlib9-' + expected + '.z') if self.compression_cache else None
            compressed = None
            if page.get('textureEncoding', 'raw') == 'raw' and compressed_path and compressed_path.is_file():
                candidate = compressed_path.read_bytes()
                probe = {**page, 'textureEncoding': 'zlib', 'textureBytes': int(page['pixelSize'][0]*page['pixelSize'][1]*4),
                         'textureSha256': expected}
                try:
                    raw = old.decode_texture(probe, candidate)
                    compressed = candidate
                except ValueError:
                    pass
            if compressed is None:
                payload = self.source(source_dir + '/' + name, expected)
                raw = old.decode_texture(page, payload)
                compressed = payload if page.get('textureEncoding') == 'zlib' else zlib.compress(raw, 9)
                compressed_path = None
            info = self.put(compressed, link=compressed_path)
            stat = (self.delivery / refs.blob_name(info['sha256'])).stat()
            result = {'file': info, 'blobStat': [stat.st_size, stat.st_mtime_ns],
                      'textureBytes': len(raw), 'textureSha256': old._sha(raw)}
            refs.atomic(receipt, old.encoded(result))
            return result

    def project(self, visual):
        source_dir = old._path(visual['spec'], 'presentation/assets/')
        checksums = visual['checksums']
        identity = old._sha(old.encoded({'source': source_dir, 'checksums': checksums}))
        if identity in self.projects:
            return self.projects[identity]
        receipt = self.delivery / 'work/projects' / (identity + '.json')
        with file_lock(receipt.with_suffix('.lock')):
            source_stats = {}
            for name in checksums:
                old.safe_name(name)
                if '/' in name: raise ValueError('Invalid project filename')
                stat = old._disk(self.root / 'data/ffbe', source_dir + '/' + name).stat()
                source_stats[name] = [stat.st_size, stat.st_mtime_ns]
            if receipt.is_file():
                cached = json.loads(receipt.read_bytes())
                if cached['sourceStats'] == source_stats and all(
                    (self.delivery / refs.blob_name(info['sha256'])).is_file() and
                    (self.delivery / refs.blob_name(info['sha256'])).stat().st_size == info['size']
                    for info in cached['files'].values()):
                    self.projects[identity] = cached
                    return cached
            spec = old._json(self.source(source_dir + '/spec.json', checksums['spec.json']))
            maps = spec.get('cellmaps', [spec])
            packed, new_checksums = {}, {}
            for i, page in enumerate(maps):
                name = page.get('textureFile', 'tex' + (f'_{i}' if i else '') + '.bgra')
                expected = old._digest(checksums[name])
                texture = self.texture(page, expected, source_dir, name)
                packed_name = name if name.endswith('.bgra.z') else name + '.z'
                page.update(textureFile=packed_name, textureEncoding='zlib', textureBytes=texture['textureBytes'], textureSha256=texture['textureSha256'])
                packed[packed_name] = texture['file']
                new_checksums[packed_name] = texture['file']['decodedSha256']
            if 'cellmaps' in spec:
                for key in ('textureFile', 'textureEncoding', 'textureBytes', 'textureSha256'):
                    spec[key] = maps[0][key]
            spec_raw = old.encoded(spec)
            spec_sha = old._sha(spec_raw)
            directory = 'presentation/assets/shared/' + spec_sha
            packed['spec.json'] = self.put(spec_raw, compress=True)
            new_checksums['spec.json'] = spec_sha
            result = {'sourceStats': source_stats, 'spec': 'data/ffbe/' + directory, 'checksums': new_checksums,
                      'files': {directory + '/' + name: info for name, info in packed.items()}}
            refs.atomic(receipt, old.encoded(result))
            self.projects[identity] = result
            return result

    def bank(self, path):
        name = old._path(path, 'audio/')
        if name in self.banks: return self.banks[name]
        raw = self.source(name)
        bank = old._json(raw)
        if bank.get('schema') != 'ffr-audio-1': raise ValueError('Invalid prepared audio bank')
        new_name = 'audio/effects/' + old._sha(raw) + '.json'
        files = {new_name: self.put(raw, compress=True)}
        for wave in bank['waves'].values():
            digest = old._digest(wave['sha256'])
            sample_name = 'audio/samples/' + digest + '.hca'
            sample = self.source(sample_name, digest)
            if len(sample) != wave['size']: raise ValueError('Prepared sample size mismatch')
            files[sample_name] = self.put(sample)
        result = 'data/ffbe/' + new_name, files
        self.banks[name] = result
        return result

    def pack(self, document, base_unit, output, coverage):
        presentation = deepcopy(document)
        form = old.form_id(presentation['form'])
        files, moves = {}, {}
        for key, move in presentation['moves'].items():
            names = set()
            for visual in move.get('visuals', []):
                project = self.project(visual)
                visual.update(spec=project['spec'], checksums=project['checksums'])
                files.update(project['files']); names.update(project['files'])
            banks = set(move.get('audioBanks', {}).values())
            if move.get('audioBank'): banks.add(move['audioBank'])
            mapping = {}
            for path in sorted(banks):
                mapping[path], dependencies = self.bank(path)
                files.update(dependencies); names.update(dependencies)
            if move.get('audioBank'): move['audioBank'] = mapping[move['audioBank']]
            if move.get('audioBanks'): move['audioBanks'] = {kind: mapping[path] for kind, path in move['audioBanks'].items()}
            moves[key] = sorted(names)
        index = {'schema': refs.VERSION, 'form': form, 'files': files, 'moves': moves, 'coverage': coverage,
                 'presentationSha256': old._sha(old.encoded(presentation))}
        refs.validate(index, presentation, form)
        payload = old.read_archive(base_unit)
        sprite_forms = {name.split('/')[1] for name in payload if name.startswith('sprites/') and len(name.split('/')) > 2}
        if sprite_forms != {form} or f'lb_profiles/{form}.json' not in payload or not any(n.startswith('unit_records/') for n in payload):
            raise ValueError('Base unit archive belongs to a different form or is incomplete')
        kit = old._json(payload[f'native_kits/{form}.json'])
        for key, move in presentation['moves'].items():
            snapshot = kit['profiles'][key]['snapshot']
            records = [{k: r.get(k) for k in ('source', 'kind', 'id', 'level', 'data')} for r in snapshot['records']]
            if old._sha(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()) != move['sourceSha256']:
                raise ValueError('Base unit and prepared move have different sources: ' + key)
        # Base units may contain legacy preview presentations; replace metadata.
        for name in list(payload):
            if name.startswith('presentation/'): del payload[name]
        payload[f'presentation/{form}.json'] = old.encoded(presentation)
        payload[f'presentation/effects/{form}.json'] = old.encoded(index)
        refs.verify_thin(payload, form)
        result = old._write_archive(output, payload)
        unique = {i['sha256']: i['size'] for i in files.values()}
        return {**result, 'format': 'ffr-unit-1', 'form': form, 'effects': refs.VERSION,
                'presentation': presentation['schema'], 'nativeKit': True,
                'preparedMoveCount': len(moves), 'effectBytesIfAllEquipped': sum(unique.values()),
                'moveDownloadBytes': {key: sum({files[n]['sha256']: files[n]['size'] for n in names}.values())
                                      for key, names in moves.items()}, **coverage}
