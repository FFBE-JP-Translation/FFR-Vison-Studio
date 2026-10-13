"""Prepare reusable sound/particle bundles for explicitly selected vision forms.

Example: python tools/ffbe_effects/prepare_vision.py 340000107 340000117
Conversion is selected by form and source move. It never changes abilities or grants.
"""
import argparse
import csv
from collections import defaultdict
from copy import deepcopy
from functools import lru_cache
import hashlib
import html
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/devui'), str(ROOT/'tools/release'), str(Path(__file__).parent)]
import catalog
import ibmb
import render
import to_ss6
import scene
import screen_adapter
import source_placement
from ffbe_effects import host_coordinates
import prepared_reuse
import rendered_coverage
from ffbe_effects.conversion_io import file_lock
from atomic_files import write_json
import ffbe_presentation as presentation
import ffbe_catalog
from ability_converter import commands
from unit_assets import AudioLibrary

REVISION = 2
EXPORT_REVISION = 10
ASSETS = ROOT/'data/ffbe/presentation/assets'
SOURCES = ROOT/'build/ffbe_cpk/effects_dec'
WORK = ROOT/'build/sora-presentation'
CACHE = None  # Offline batch shares content-addressed bakes across every move.


@lru_cache(maxsize=4)
def _audio_library(name, root, modified, size):
    return AudioLibrary(name, Path(root)/'data/ffbe/audio/samples')


def audio_library(name):
    path = ROOT/'data/ffbe/audio'/(name+'.acb')
    if not path.is_file(): path = Path('S:/FFBE JP Data Export/public')/(name+'.acb')
    info = path.stat()
    return _audio_library(name, str(ROOT), info.st_mtime_ns, info.st_size)


@lru_cache(maxsize=2)
def _native_kit(path, modified, size):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def native_kit(form):
    path = ROOT / f'data/ffbe/native_kits/{form}.json'
    stat = path.stat()
    return _native_kit(str(path), stat.st_mtime_ns, stat.st_size)


def write(path, doc):
    write_json(path, doc, ensure_ascii=False, separators=(',', ':'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_effect_frames(data, *, source_matched=False):
    """JP client snapshots retain raw scheduling under _master, not always a normalized list."""
    value=data.get('effect_frames')
    if value is None and source_matched:
        value=data.get('_master',{}).get('effect_frames')
        if value is None:
            return None
    if isinstance(value,str):
        return [int(fields[0]) for component in value.split('@') for fields in catalog.parse_frames(component)]
    return [v for group in (value or []) for v in group]


def timeline(snapshot, screen_placement=None, include_screen=False, *, source_matched=False):
    """Resolve exact IDs and only immediate retained root/child components."""
    root = snapshot['root']
    profile = commands.from_snapshot(snapshot, reviewed=True)
    allowed = set()
    for c in profile['conversion']['components']:
        for item in c['actions'] + c['effects']:
            allowed.add(item.get('source') or root)
    visuals, sounds, issues, provenance = [], [], [], []
    omitted_visuals = []
    placement_groups = []
    # A cooldown/trigger wrapper can delegate all retained mechanics to its
    # child, while the actor still uses the root command's motion selector.
    # Read it before filtering effect provenance by retained components.
    root_parts = root.split('/')
    root_record = next((record for record in snapshot['records']
                        if record['source'] == root_parts[0] and record['kind'] == root_parts[1]
                        and str(record['id']) == root_parts[2]), None)
    root_catalog = (catalog.skill_effects(root_record['kind'], root_record['id'], source=root_record['source'])
                    if source_matched else catalog.skill_effects(root_record['kind'], root_record['id'])) if root_record else None
    for record in snapshot['records']:
        key = '/'.join([record['source'], record['kind'], str(record['id'])])
        if record.get('level') is not None: key += '/level/' + str(record['level'])
        if key not in allowed: continue
        own = commands.from_snapshot({**snapshot, 'root': key}, reviewed=True)
        kept = {c['index'] for c in own['conversion']['components'] if c['actions'] or c['effects']}
        data = (catalog.skill_effects(record['kind'], record['id'], source=record['source'])
                if source_matched else catalog.skill_effects(record['kind'], record['id']))
        if data is None:
            issues.append(f'{key}: no matching JP presentation record')
            omitted_visuals.append({'source':key,'reason':'missing presentation record'}); continue
        # GL kit and JP presentation identity must agree on effect start frames.
        expected = snapshot_effect_frames(record['data'],source_matched=source_matched)
        actual = [g['frame'] for g in data['groups']]
        if expected != actual:
            issues.append(f'{key}: regional effect-frame mismatch; presentation held')
            omitted_visuals.append({'source':key,'reason':'regional effect-frame mismatch'})
            continue
        provenance.append({'source': key, 'catalog': data, 'retainedComponents': sorted(kept)})
        for g in data['groups']:
            if g['component'] not in kept:
                issues.append(f'{key} component {g["component"]}: omitted mechanics; visual and sound omitted')
                continue
            group = g['group']
            if not group:
                if g['groupId'] != '99999999':
                    issues.append(f'Missing effect group {g["groupId"]}')
                    omitted_visuals.append({'groupId':g['groupId'],'reason':'missing effect group'})
                continue
            flags = g['flags']
            native_placement = source_placement.normalize_skill_placement(flags)
            source_effects = [source_placement.normalize_effect_placement(fields)
                              for fields in catalog.parse_frames(group.get('sourceEffectFrames', ''))]
            placement_groups.append({'source': key, 'groupId': g['groupId'], 'frame': g['frame'],
                                     'skill': native_placement, 'effects': source_effects})
            # Placement support affects the visual adapter, not the source
            # group's sound clock. Projectile groups may carry hit cues even
            # while their travel/rectangle adapter is still unavailable.
            for sound in group['sounds']:
                flag = int((sound.get('extra') or ['1'])[0])
                sounds.append({'frame': g['frame'] + sound['frame'], 'cueId': int(sound['seId']),
                               'sourceBank': 'SE' if flag == 1 else 'System'})
            if not source_matched and (len(flags) != 3 or flags[2] != '0'):
                reason = ('source placement awaits native rectangle/travel adapter'
                          if native_placement['supported'] else 'unresolved placement flags')
                issues.append(f'Group {g["groupId"]}: {reason} {flags}')
                omitted_visuals.append({'groupId':g['groupId'],'reason':reason}); continue
            if not native_placement['supported']:
                issues.append(f'Group {g["groupId"]}: unresolved placement flags {flags}')
                omitted_visuals.append({'groupId':g['groupId'],'reason':'unresolved placement flags'}); continue
            layer, anchor = native_placement['layer']['sourceValue'], native_placement['anchorValue']
            if anchor not in ((1, 2, 3, 7) if source_matched else (1, 2, 3)) and not (anchor == 4 and (screen_placement or include_screen)):
                issues.append(f'Group {g["groupId"]}: {"screen overlay" if anchor == 4 else "projectile anchor " + str(anchor)} awaits an adapter')
                omitted_visuals.append({'groupId':g['groupId'],'reason':'unsupported anchor'})
                continue
            if layer not in (1, 2):
                issues.append(f'Group {g["groupId"]}: unknown draw layer {layer}')
                omitted_visuals.append({'groupId':g['groupId'],'reason':'unknown draw layer'}); continue
            for effect_index, effect in enumerate(group['effects']):
                if not effect['exists']:
                    reason = effect.get('sourceIssue') or 'missing particle'
                    issues.append(f'{effect["file"]}: {reason}')
                    omitted_visuals.append({'file':effect['file'],'reason':reason}); continue
                visuals.append({**effect, 'frame': g['frame'] + effect['frame'], 'layer': layer,
                                'anchor': {1:'each_target', 2:'target_group', 3:'caster', 4:'screen',7:'caster'}[anchor],
                                'source': key, 'component': g['component'], 'groupId': g['groupId'],
                                **({'sourceGroupFrame':g['frame'],'sourceSkillPlacement':deepcopy(native_placement),
                                    'sourceEffectPlacement':deepcopy(source_effects[effect_index])}
                                   if source_matched and effect_index < len(source_effects) else {})})
    # BattleUnit::initMoveBefore creates these two standard ability groups at
    # preaction start, then waits 10 frames. They are not listed in the move's
    # effect_frames and must not share the main-action clock. Their SE100 cue
    # is supplied by the common casting-audio adapter (group-local frame 1).
    cast_groups = []
    if root.split('/')[1] == 'ability':
        cast_groups = [('9000110', 1), ('9000120', 2)]
    elif root.split('/')[1] == 'magic':
        # Source magic school selects its standard activation pair. Ultima is black.
        school = str((root_record or {}).get('data', {}).get('magic_type', '')).lower()
        pairs = {'white': ('9000030', '9000040'), 'black': ('9000050', '9000060'),
                 'green': ('9000070', '9000080'), 'blue': ('9000090', '9000100')}
        if school in pairs:
            cast_groups = list(zip(pairs[school], (1, 2)))
        else:
            issues.append('Magic activation school unresolved; common casting audio retained')
    if cast_groups:
        for group_id, layer in cast_groups:
            group = (catalog.group_detail(group_id, source=root_parts[0])
                     if source_matched else catalog.group_detail(group_id))
            if not group:
                issues.append(f'Missing standard ability cast group {group_id}')
                continue
            for effect in group['effects']:
                if effect['exists']:
                    visuals.append({**effect, 'layer': layer, 'anchor': 'caster', 'phase': 'cast',
                                    'source': root, 'component': None, 'groupId': group_id})
                else:
                    issues.append(f'Missing standard ability cast particle {effect["file"]}')
    # Same cue in two simultaneous layers is one audible impact in this adapter.
    unique_sounds = {(s['frame'], s['sourceBank'], s['cueId']): s for s in sounds}
    if len(unique_sounds) < len(sounds):
        issues.append(f'{len(sounds)-len(unique_sounds)} simultaneous duplicate sound events coalesced')
    has_source_placement = any(group['effects'] for group in placement_groups)
    if has_source_placement:
        issues.append('Source rectangle alignment, per-spawn jitter and reverse-side selection are recorded; '
                      'the current visual adapter still uses legacy anchor offsets')
    result = {'sounds': sorted(unique_sounds.values(), key=lambda s:(s['frame'],s['cueId'])),
            'spawns': visuals, 'issues': issues, 'provenance': provenance,
            'sourcePlacement': {'nativeContract': source_placement.NATIVE_CONTRACT,
                                'hostAdapter': 'legacy_anchor_offset_only',
                                'applied': False if has_source_placement else None,
                                'groups': placement_groups},
            'visualCoverage': {'complete':not omitted_visuals, 'omitted':omitted_visuals},
            'targetType': profile['set'].get('TargetType'), 'supported': profile['supported'],
            **({'sourceMoveType': root_catalog.get('move_type')} if source_matched and root_catalog else {}),
            'motionType': int(root_catalog['motion']) if root_catalog and root_catalog.get('motion') is not None else None,
            **({'cast': {'bank': 'SE', 'cueName': 'se_special_flash_1', 'frame': 1,
                         'durationFrames': 10, 'motion': 'command'}}
               if root.split('/')[1] == 'ability' else {})}
    if source_matched:
        normalize_preroll(result)
    return result


def normalize_preroll(timeline):
    """Retain signed source offsets by translating the whole action clock.

    Some resurrection effects dispatch before action frame zero. FFR's exported
    timeline starts at zero; shifting all action events preserves their spacing.
    Cast particles use their independent preaction clock and are never shifted.
    """
    action = [s for s in timeline['spawns'] if s.get('phase', 'action') != 'cast']
    clocks = [s['frame'] for s in action + timeline['sounds']]
    clocks += [s['sourceGroupFrame'] for s in action if 'sourceGroupFrame' in s]
    offset = -min(0, min(clocks, default=0))
    if not offset: return
    for event in action + timeline['sounds']:
        event['sourceSignedFrame'] = event['frame']
        event['frame'] += offset
    for event in action:
        if 'sourceGroupFrame' in event:
            event['sourceSignedGroupFrame'] = event['sourceGroupFrame']
            event['sourceGroupFrame'] += offset
    timeline['sourcePrerollFrames'] = offset
    timeline['issues'].append('Signed source pre-roll is translated to a zero-based action clock; native dispatch-state timing is approximated')


def bake_source(filename, texture_cache, seed=12345, max_frames=None, particle_budget=256,
                canonical_variation=False):
    # A shared source can be requested by multiple form workers at once.
    key = hashlib.sha256(filename.encode()).hexdigest()
    with file_lock((CACHE or WORK/'decoded')/'.locks'/(key+'.lock')):
        return _bake_source_locked(filename, texture_cache, seed, max_frames,
                                   particle_budget, canonical_variation)


def _bake_source_locked(filename, texture_cache, seed=12345, max_frames=None, particle_budget=256,
                        canonical_variation=False):
    source = SOURCES / filename
    effect = ibmb.parse(str(source))
    if max_frames is None and effect.duration >= 0x7fffffff:
        raise ValueError(f'{filename}: unbounded source lifetime requires a finite owning-action window')
    if max_frames is not None and (type(max_frames) is not int or max_frames <= 0):
        raise ValueError('Particle frame limit must be a positive integer')
    dependencies = [source]
    for name, ext in [(t, '.png') for t in effect.textures] + [(m, '.m3r') for m in effect.models]:
        p = SOURCES / (name if Path(name).suffix else name + ext)
        if p.is_file(): dependencies.append(p)
    frame_limit = max(1, min(effect.duration, max_frames) if max_frames is not None else effect.duration)
    stamp = {'revision': REVISION, 'decoder': ibmb.BAKE_VERSION,
             'dependencies': {p.name: digest(p) for p in dependencies},
             'maxFrames': frame_limit, 'maxParticles': particle_budget, 'maxSprites': 256, 'seed': seed,
             'canonicalVariation': canonical_variation}
    key = hashlib.sha256(json.dumps(stamp, sort_keys=True).encode()).hexdigest()[:16]
    folder = (CACHE or WORK/'decoded')/key
    doc_path = folder/'doc.json'
    if doc_path.is_file() and (folder/'audit.json').is_file():
        cached_doc = json.loads(doc_path.read_text(encoding='utf-8'))
        # Earlier exports recorded a virtual-texture JSON label when a mesh
        # projected to zero pixels. Rebuild only those invalid cached docs.
        if not any(name.startswith('nativeuv:') for name in cached_doc.get('textures', [])):
            return cached_doc, json.loads((folder/'audit.json').read_text())
    print('Decoding', filename, flush=True)
    baked = ibmb.bake(effect, max_frames=frame_limit, max_particles=particle_budget, seed=seed,
                     canonical_variation=canonical_variation)
    # Compare against a higher emission budget, not simply an assumed cap hit.
    reference = ibmb.bake(effect, max_frames=frame_limit, max_particles=particle_budget*4, seed=seed,
                         canonical_variation=canonical_variation)
    before = sum(len(f) for f in reference['frames'])
    after = sum(len(f) for f in baked['frames'])
    all_doc = render.build_doc(baked, texture_cache, 2.4, 1., max_sprites=100000)
    doc = {**all_doc, 'frames': [f[:256] for f in all_doc['frames']]}
    # Preserve all source frames with visible content, including long LBs,
    # while avoiding a long idle wait after a declared but empty effect tail.
    visible_end = next((i + 1 for i in range(len(doc['frames']) - 1, -1, -1) if doc['frames'][i]), 1)
    doc['frames'] = doc['frames'][:visible_end]
    doc['frameCount'] = visible_end
    issues = []
    alpha_fidelity = baked.get('alphaFidelity')
    if alpha_fidelity:
        for fallback in alpha_fidelity.get('fallbacks', []):
            issues.append(f'Object {fallback["chunk"]}: opacity mode {fallback["mode"]}: {fallback["reason"]}')
    variation = baked.get('canonicalVariation')
    if variation and variation['unsupportedLineageEmitters']:
        issues.append('Fixed variation lacks native instance lineage for emitters: ' +
                      ', '.join(map(str, variation['unsupportedLineageEmitters'])))
    if before > after: issues.append(f'{before-after} particle frame instances exceed emitter budget')
    dropped = sum(max(0, len(f)-256) for f in all_doc['frames'])
    if dropped: issues.append(f'{dropped} sprite frame instances exceed export budget')
    if effect.models: issues.append('3D mesh emitters use projected sprites')
    missing = [t for t in effect.textures if t.lower() in texture_cache.missing]
    if missing: issues.append('Missing textures: ' + ', '.join(missing))
    missing_models = [m for m in effect.models if not (SOURCES/(m+'.m3r')).is_file()]
    if missing_models: issues.append('Missing meshes: ' + ', '.join(missing_models))
    for chunk in effect.chunks:
        if chunk.enabled:
            material = ibmb._native_texture_material(chunk, 0)
            if material:
                for unsupported in material['unsupported']:
                    issues.append(f'Object {chunk.index}: unsupported texture material {unsupported}')
            active_channels = len(chunk.uv_channels) if material and material['mode'] else min(1, len(chunk.uv_channels))
            for channel in range(active_channels):
                state = ibmb._native_uv_channel(chunk, channel, 0)
                for unsupported in state['unsupported']:
                    issues.append(f'Object {chunk.index} texture {channel+1}: unsupported UV {unsupported}')
        if chunk.translation_mode in (6, 8):
            issues.append(f'Object {chunk.index}: randomized translation curves remain approximate')
        kind = chunk.scale_mode - 14 if chunk.scale_mode is not None and chunk.scale_mode >= 15 else chunk.scale_mode
        if kind not in (1, 2, 3, 4, 5, 6):
            if chunk.is_node or chunk.is_emitter:
                issues.append(f'Object {chunk.index}: scaling mode {chunk.scale_mode} remains approximate')
        elif kind == 6 or (not canonical_variation and any(any(v for v in (getattr(chunk, name) or []))
                              for name in ('scale_variance', 'scale_velocity_variance', 'scale_acceleration_variance'))):
            issues.append(f'Object {chunk.index}: randomized scaling uses authored mean')
        if chunk.rotation_mode not in (0, 1, 2, 3, 4, 6):
            if chunk.is_node or chunk.is_emitter:
                issues.append(f'Object {chunk.index}: rotation mode {chunk.rotation_mode} remains approximate')
        elif not canonical_variation and chunk.rotation_mode in (1, 2, 3, 6):
            active = ['rotation_variance']
            if chunk.rotation_mode in (2, 3): active.append('rotation_velocity_variance')
            if chunk.rotation_mode == 3: active.append('rotation_acceleration_variance')
            if any(any(v for v in (getattr(chunk, name) or [])) for name in active):
                issues.append(f'Object {chunk.index}: randomized rotation uses authored mean')
    for emitter in effect.emitters():
        if not emitter.life: issues.append(f'Emitter {emitter.index}: lifetime approximated from node window')
    audit = {**stamp, 'file': filename, 'frames': doc['frameCount'],
             'declaredFrames': effect.duration, 'emptyTailFrames': frame_limit - visible_end,
             'actionLifetimeFrames': max_frames,
             'variation': variation,
             'alphaFidelity': alpha_fidelity,
             'peakSprites': max(map(len, doc['frames']), default=0),
             'issues': sorted(set(issues)), 'textures': doc['textures']}
    write(doc_path, doc); write(folder/'audit.json', audit)
    return doc, audit


def resolve_screen_group_overscan(config, spawns, placement):
    """Validate an explicit host framing adjustment against retained source groups."""
    if config is None:
        return {}
    if not isinstance(config, dict) or set(config) != {'groupIds', 'scale'}:
        raise ValueError('Screen group overscan requires only groupIds and scale')
    ids, scale = config['groupIds'], config['scale']
    if (not isinstance(ids, list) or not ids or any(not isinstance(g, str) or not g.isdecimal() for g in ids)
            or len(ids) != len(set(ids))):
        raise ValueError('Screen group overscan requires unique source group IDs')
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale < 1:
        raise ValueError('Screen group overscan scale must be finite and at least one')
    presentation.validate_screen_placement(placement)
    retained = {s.get('groupId') for s in spawns}
    if set(ids) - retained:
        raise ValueError('Screen group overscan refers to a missing retained source group')
    if any(s.get('anchor') != 'screen' for s in spawns if s.get('groupId') in ids):
        raise ValueError('Screen group overscan cannot modify caster or target effects')
    return dict.fromkeys(ids, float(scale))


def compose(spawns, docs, screen_group_scales=None, *, background_detection=None,
            background_rectangle=None, background_audits=None, screen_camera_groups=None,
            flash_rectangle=None, flash_audits=None):
    first = min(s.get('hostCoordinates',{}).get('sampleFrame',s['frame']) for s in spawns)
    count = max(s['frame']-first + len(docs[s['file']]['frames']) for s in spawns) + 4
    textures, indices, frames = [], {}, [[] for _ in range(count)]
    screen_group_scales = screen_group_scales or {}
    screen_camera_groups = screen_camera_groups or {}
    transformed = {}
    for spawn in spawns:
        doc = docs[spawn['file']]
        if background_rectangle and background_detection:
            # The same BMB can be instantiated at several anchors. Fit a copy
            # for this particular rear-screen spawn, never the shared source.
            doc, fit = scene.cover_background(doc, background_detection, [spawn],
                                               background_rectangle, to_ss6.load_texture)
            if fit['spriteFrames'] and background_audits is not None:
                previous=background_audits.setdefault(spawn['file'],{**fit,'spriteFrames':0})
                previous['spriteFrames']+=fit['spriteFrames']
                previous['maxScale']=max(previous['maxScale'],fit['maxScale'])
        if flash_rectangle:
            doc, fit = scene.cover_flat_flashes(doc,[spawn],flash_rectangle,to_ss6.load_texture)
            if fit['spriteFrames'] and flash_audits is not None:
                previous=flash_audits.setdefault(spawn['file'],{**fit,'spriteFrames':0})
                previous['spriteFrames']+=fit['spriteFrames']
                previous['maxScale']=max(previous['maxScale'],fit['maxScale'])
        group_scale = screen_group_scales.get(spawn.get('groupId'), 1.0)
        camera_adapter=screen_camera_groups.get(spawn.get('groupId'))
        if camera_adapter:
            group_scale=1.0
        if group_scale != 1 and spawn.get('anchor') != 'screen':
            raise ValueError('Screen group overscan cannot modify caster or target effects')
        remap = {}
        for i, tex in enumerate(doc['textures']):
            if tex not in indices: indices[tex] = len(textures); textures.append(tex)
            remap[i] = indices[tex]
        for fi, frame in enumerate(doc['frames']):
            for item in frame:
                sp = deepcopy(item); sp['tex'] = remap[sp['tex']]
                # FFBE offsets are +right/+down, document positions +right/+up.
                angle=math.radians(spawn.get('rotation',[0,0,0])[2])
                x,y=item['pos']; c,s=math.cos(angle),math.sin(angle)
                offset_x,offset_y=spawn.get('hostCoordinates',{}).get('sourceOffset',[spawn['x'],spawn['y']])
                sp['pos'] = [(x*c-y*s)*spawn['scale'] + offset_x*2.4,
                             (x*s+y*c)*spawn['scale'] - offset_y*2.4]
                sp['rot'] += math.degrees(angle)
                sp['scale'] = [v*spawn['scale'] for v in item['scale']]
                frame_index = spawn['frame']-first+fi+2
                if camera_adapter:
                    # The two SS6 lead frames are canceled by the native
                    # event's -800 tick start. Follow the original source clock.
                    sp=screen_adapter.transform(sp,spawn,spawn['frame']+fi,camera_adapter)
                if group_scale != 1:
                    # The shared screen offset is applied after composition.
                    # Scaling around zero here therefore scales around that
                    # offset in the final plane, never around the moving caster.
                    sp['pos'] = [v * group_scale for v in sp['pos']]
                    sp['scale'] = [v * group_scale for v in sp['scale']]
                    blend = 'add' if str(sp.get('blend', 'mix')).lower() in ('add', 'additive', 'screen') else 'mix'
                    part = f'{blend}_{len(frames[frame_index])}'
                    group = transformed.setdefault(spawn['groupId'], {'scale': group_scale, 'parts': {}})
                    group['parts'].setdefault(part, []).append(frame_index)
                frames[frame_index].append(sp)
    result = {'fps':60, 'frameCount':count, 'pixelsPerUnit':2.4,
              'textures':textures, 'frames':frames}
    if transformed:
        result['groupTransforms'] = transformed
    return first, result


def preview(doc, path):
    """A decoder preview, not a claim of matching FFR's lighting/blending."""
    import numpy as np
    from PIL import Image
    @lru_cache(maxsize=32)
    def texture(index):
        return np.asarray(to_ss6.load_texture(doc['textures'][index]), dtype=np.float32)/255
    result = []
    step = max(4, len(doc['frames'])//60)
    for fi in range(0, len(doc['frames']), step):
        canvas = np.zeros((384, 384, 4), dtype=np.float32)
        canvas[:,:,:3] = [0.055,0.065,0.09]; canvas[:,:,3] = 1
        for sp in doc['frames'][fi]:
            tex = texture(sp['tex'])
            w,h = abs(sp['scale'][0])*tex.shape[1]*.28, abs(sp['scale'][1])*tex.shape[0]*.28
            if w<.5 or h<.5: continue
            patch=render._prepare_sprite(tex,min(w,768),min(h,768),sp['rot'],sp.get('flipX'),sp.get('flipY'))
            render._blit(canvas,patch,192+sp['pos'][0]*.28,192-sp['pos'][1]*.28,
                         sp.get('color',[1,1,1]),sp['alpha']*.65 if sp['blend']=='add' else sp['alpha'],
                         'add' if sp['blend']=='add' else 'normal')
        result.append(Image.fromarray((np.clip(canvas,0,1)*255).astype(np.uint8),'RGBA'))
    result[0].save(path,save_all=True,append_images=result[1:],duration=round(step*1000/60),loop=0,quality=72)


def source_action_timing(form, source_key, motion_type, profile):
    """Read the action's CGS clock; an effect container's lifetime is not it."""
    explicit=profile.get('actionLifetimeFrames')
    if explicit is not None:
        if type(explicit) is not int or explicit<=0:
            raise ValueError('Action lifetime must be a positive source frame count')
        return explicit,profile.get('actionLifetimeEvidence','explicit source profile')
    motion='limitatk' if '/lb/' in source_key else 'magicatk' if motion_type==2 else 'atk'
    directory,source_form=ffbe_catalog.anim_source(form,motion)
    filename=ffbe_catalog.cgs_file(directory,source_form,motion) if directory else None
    if filename:
        path=Path(filename)
        with path.open(encoding='utf-8-sig',newline='') as stream:
            rows=[row for row in csv.reader(stream) if row and any(row)]
        if rows and all(len(row)>=4 for row in rows):
            evidence=path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
            return sum(max(1,int(row[3])) for row in rows),evidence
    return None,'source CGS action duration unavailable or ambiguous'


@lru_cache(maxsize=256)
def universal_unit_geometry(form, source):
    rows=catalog.table('F_UNIT_MST',source=source)
    row=next((r for r in rows if str(r.get('unit_evo_id') or r.get('unit_id'))==str(form)),None)
    issues=[]
    if row is None:
        row={'TouchRect':'','MoveOffset':'','MoveSpeed':'0'}
        issues.append('Unit geometry row missing from matching source; a 64-pixel root proxy is used')
    directory,source_form=ffbe_catalog.anim_source(form,'idle')
    try:
        geometry=host_coordinates.load_unit_geometry_from_folder(row,directory,source_form or form)
    except (ValueError,OSError) as error:
        geometry=host_coordinates.parse_unit_geometry({'TouchRect':'','MoveOffset':'','MoveSpeed':'0'},[64,64])
        issues.append(f'Source unit geometry unavailable ({error}); a 64-pixel root proxy is used')
    geometry.setdefault('approximations',[]).extend(issues)
    geometry['source']=source
    return geometry


def prepare(forms, selected_moves=None, profile=None, *, detect_scene=False, merge_existing=False,
            retain_prepared=False, manifest_out=None, rebuild_sources=None, make_previews=True,
            universal=False, host_preferences=None):
    host_preferences = deepcopy(host_preferences or {})
    if (not isinstance(host_preferences, dict)
            or set(host_preferences) - {'hostTargetType'}):
        raise ValueError('Universal host preferences accept only hostTargetType')
    presentation.host_target_settings({'reconstructionProfile':host_preferences})
    profile = profile or {}
    export = profile.get('export', {})
    if profile and (forms != [profile.get('form')] or selected_moves != [profile.get('sourceKey')]):
        raise ValueError('A reconstruction profile must match the single selected form and move')
    if detect_scene and (len(forms)!=1 or not selected_moves or len(selected_moves)!=1):
        raise ValueError('Automatic scene preparation requires one selected move per call')
    explicit_profile = bool(profile)
    requested_profile = deepcopy(profile) if explicit_profile else None
    if manifest_out is not None and len(forms) != 1:
        raise ValueError('A staged manifest requires exactly one form')
    if retain_prepared and not detect_scene:
        raise ValueError('Retained preparation requires the complete source scene timeline')
    if rebuild_sources and not retain_prepared:
        raise ValueError('Rebuilding selected sources requires retained preparation')
    if universal and retain_prepared:
        raise ValueError('Universal source coordinates require fresh conversion, not retained legacy groups')
    if detect_scene and not profile:
        profile = scene.default_profile(forms[0], selected_moves[0], {'kind':'battlefield'})
        export = profile['export']
    WORK.mkdir(parents=True,exist_ok=True)
    texture_cache=render.TextureCache([str(SOURCES)])
    audio=audio_library('SE')
    prepared, asset_audit, docs, retained, previous_moves = {}, {}, {}, {}, {}
    for form in forms:
        native=native_kit(form)
        kit=native['kit']
        prior_path = Path(manifest_out) if manifest_out is not None and Path(manifest_out).is_file() else presentation.BUNDLES/(form+'.json')
        prior_bundle = json.loads(prior_path.read_text(encoding='utf-8')) if prior_path.is_file() else None
        if prior_bundle and (str(prior_bundle.get('form')) != form or prior_bundle.get('schema') != presentation.VERSION):
            raise ValueError('Existing prepared manifest belongs to another form or schema')
        entries=[]
        for e in kit['entries']:
            if e['kind']=='PASSIVE' or e['status']!='ready':continue
            if selected_moves and e['sourceKey'] not in selected_moves: continue
            snapshot=native['profiles'][e['sourceKey']]['snapshot']
            previous = (prior_bundle or {}).get('moves',{}).get(e['sourceKey']) if retain_prepared else None
            preserve_profile = bool(previous and previous.get('reconstructionProfile') and not explicit_profile)
            if preserve_profile:
                profile = deepcopy(previous['reconstructionProfile'])
                if str(profile.get('form')) != form or profile.get('sourceKey') != e['sourceKey']:
                    raise ValueError('Retained reconstruction profile belongs to another form or source')
                export = profile.get('export',{})
            screen_placement = profile.get('screenPlacement')
            data=timeline(snapshot, screen_placement, include_screen=detect_scene,source_matched=universal)
            if universal:
                geometry=universal_unit_geometry(form,e['sourceKey'].split('/')[0])
                data=host_coordinates.adapt_timeline(data,geometry,
                    reference_stage=(screen_placement or {}).get('referenceStage',[320,320]),
                    seed=profile.get('seed',12345))
            entry={'name':e['name'],'sourceKey':e['sourceKey'],'sourceSha256':presentation.source_fingerprint(snapshot),**data}
            if universal and '/lb/' in e['sourceKey']:
                entry['sourceMovement']=host_coordinates.ground_approach_offset(geometry,limit_burst=True,
                    scale=host_coordinates.HostScale(export_scale=export.get('scaleMult',1.6),
                        runtime_scale=export.get('runtimeScale',export.get('casterRuntimeScale',1.0))))
                entry['issues'].append('Ground approach translates source offsets and caster width with a 64x128 target proxy; host elevation is preserved and source depth randomness is not replayed')
            source_bake_limit=profile.get('actionLifetimeFrames')
            if universal:
                action_frames,action_evidence=source_action_timing(form,e['sourceKey'],data.get('motionType'),profile)
                source_bake_limit=min(1800,max(180,action_frames or 0,
                    max((spawn['frame'] for spawn in data['spawns']),default=0)))
                entry['sourceRenderBudget']={'maxFramesPerBmb':source_bake_limit,
                    'sourceActionFrames':action_frames,'sourceActionEvidence':action_evidence,
                    'policy':'finite action-aware cap, minimum180 and maximum1800 source frames'}
                entry['issues'].append('Long or looping source particle lifetimes use a finite action-aware export window')
            reuse = {}
            if retain_prepared:
                reuse, evidence, issues = prepared_reuse.validate(previous,entry,ROOT,
                    profile if preserve_profile else requested_profile)
                reuse, evidence = prepared_reuse.rebuild_groups(reuse,evidence,entry['spawns'],rebuild_sources)
                evidence, issues = prepared_reuse.archive_rebuilt_issues(evidence,issues,entry['spawns'])
                retained[(form,e['sourceKey'])] = reuse
                previous_moves[(form,e['sourceKey'])] = previous
                entry['retainedLegacyVisuals'] = evidence
                if evidence.get('rebuiltGroups'):
                    entry['rebuiltPreparedVisuals'] = deepcopy(evidence['rebuiltGroups'])
                entry['issues'].extend(issues)
                if preserve_profile:
                    entry['reusedReconstructionProfile'] = {'policy':'reuse prior recorded profile unchanged',
                        'profile':deepcopy(profile)}
            if profile:
                entry['reconstructionProfile'] = deepcopy(profile)
                if profile.get('opening'): entry['opening'] = deepcopy(profile['opening'])
            entries.append(entry)
            for spawn in data['spawns']:
                # Retained rear screen layers are decoded for classification;
                # other retained groups need no simulation or new export.
                if prepared_reuse.group_key(spawn) in reuse and not (spawn['anchor']=='screen' and spawn['layer']==2):
                    continue
                filename=spawn['file']
                if filename not in docs:
                    docs[filename],asset_audit[filename]=bake_source(filename,texture_cache,profile.get('seed',12345),
                        source_bake_limit, profile.get('particleBudget',256),
                        profile.get('canonicalVariation', False))
            if detect_scene:
                action_frames, action_evidence=source_action_timing(form,e['sourceKey'],data.get('motionType'),profile)
                detection = scene.classify(data['spawns'], docs, to_ss6.load_texture,
                                            profile.get('screenPlacement',{}).get('referenceStage',[320,320]),
                                            action_frames=action_frames)
                detection['actionDurationSource']=action_evidence
                if action_frames is None and detection['kind']=='replacement_background':
                    detection['kind']='unresolved_screen'
                    entry['issues'].append('Screen background classification needs the source CGS action duration')
                entry['backgroundDetection'] = detection
                if not explicit_profile and not preserve_profile:
                    profile = scene.default_profile(form, e['sourceKey'], detection)
                    export = profile['export']
                elif profile.get('screenPlacement',{}).get('backdrop') and detection['kind']!='replacement_background':
                    raise ValueError('Cinematic background profile has no sustained source background evidence')
                # Gameplay preferences remain separate from source coordinates
                # and automatic scene detection. A user's target preference
                # must not resurrect an old bespoke camera or staging profile.
                profile.update(host_preferences)
                entry['reconstructionProfile']=deepcopy(profile)
        prepared[form]={'schema':presentation.VERSION,'name':kit['name'],'form':form,'moves':{e['sourceKey']:e for e in entries}}
    all_sounds={s['cueId'] for bundle in prepared.values() for e in bundle['moves'].values()
                for s in e['sounds'] if s.get('sourceBank', 'SE') == 'SE'}
    if any(e['sourceKey'].split('/')[1] == 'ability' for bundle in prepared.values() for e in bundle['moves'].values()):
        all_sounds.add(100)
    if any(e.get('opening') for bundle in prepared.values() for e in bundle['moves'].values()):
        all_sounds.add(647)
    bank=audio.selection(all_sounds)
    bank_name='presentation_'+hashlib.sha256(json.dumps(bank,sort_keys=True).encode()).hexdigest()[:16]+'.json'
    bank_path=ROOT/'data/ffbe/audio'/bank_name
    write(bank_path,bank)
    system_ids = {s['cueId'] for bundle in prepared.values() for e in bundle['moves'].values()
                  for s in e['sounds'] if s.get('sourceBank') == 'System'}
    system_path = None
    if system_ids:
        system_doc = audio_library('System').selection(system_ids)
        if system_doc['omitted']:
            raise ValueError('Required System cues unavailable: ' + str(system_doc['omitted']))
        system_path = ROOT/'data/ffbe/audio'/('presentation_system_' + hashlib.sha256(
            json.dumps(system_doc, sort_keys=True).encode()).hexdigest()[:16] + '.json')
        write(system_path, system_doc)
    previews=WORK/'previews';previews.mkdir(exist_ok=True)
    shipped_sound_omissions, sound_omissions_by_move = {}, {}
    for bundle in prepared.values():
        for entry in bundle['moves'].values():
            profile = entry.get('reconstructionProfile', profile)
            export = profile.get('export', {})
            previous = previous_moves.get((bundle['form'],entry['sourceKey']))
            entry['audioBank']=previous['audioBank'] if previous else bank_path.relative_to(ROOT).as_posix()
            if system_path:
                entry['audioBanks'] = {'SE': entry['audioBank'], 'System': system_path.relative_to(ROOT).as_posix()}
            entry_omissions = entry['retainedLegacyVisuals']['audioBankOmissions'] if previous else bank['omitted']
            entry['soundOmissions'] = deepcopy(entry_omissions)
            shipped_sound_omissions.update(entry_omissions)
            sound_omissions_by_move[entry['sourceKey']] = deepcopy(entry_omissions)
            entry['visuals']=[]
            group_scales = resolve_screen_group_overscan(export.get('screenGroupOverscan'), entry['spawns'], profile.get('screenPlacement'))
            camera_groups = screen_adapter.resolve(export.get('screenCameraGroups'),entry['spawns'],
                profile.get('screenPlacement'),export.get('screenRuntimeViewport'))
            if camera_groups:
                entry['screenCameraGroups']=deepcopy(export['screenCameraGroups'])
            groups=defaultdict(list)
            composition_docs = dict(docs)
            if universal:
                rendered_coverage.record_empty_sources(entry, entry['spawns'], docs, asset_audit)
            for spawn in entry['spawns']:
                if universal:
                    stage = profile.get('screenPlacement', {}).get('referenceStage', [320, 320])
                    remaining, flashes, flash_audit = scene.split_viewport_flashes(
                        docs[spawn['file']], spawn, to_ss6.load_texture, stage)
                    if flashes is not None:
                        # Partition only this dispatch; a shared BMB can also be
                        # used at another time, layer or anchor in the same move.
                        key = spawn['file'] + '#dispatch_' + str(len(composition_docs))
                        composition_docs[key] = remaining
                        composition_docs[key + '_flash'] = flashes
                        entry.setdefault('viewportFlashAdaptation', []).append({
                            'sourceFile': spawn['file'], 'sourceGroupId': spawn['groupId'], **flash_audit})
                        overlay = {**spawn, 'file': key + '_flash', 'anchor': 'screen',
                                   'layer': 1, 'x': 0., 'y': 0., 'scale': 1., 'rotation': [0., 0., 0.]}
                        overlay.pop('hostCoordinates', None)
                        groups[(spawn.get('phase', 'action'), 'screen', 1, 'viewport_flashes')].append(overlay)
                        spawn = {**spawn, 'file': key}
                        if 'screenPlacement' not in profile:
                            profile['screenPlacement'] = scene.default_profile(bundle['form'], entry['sourceKey'],
                                {'kind': 'screen_overlay', 'referenceStage': stage})['screenPlacement']
                            entry['reconstructionProfile'] = deepcopy(profile)
                groups[(spawn.get('phase', 'action'),spawn['anchor'],spawn['layer'],
                        spawn.get('hostCoordinates',{}).get('groupKey'))].append(spawn)
            for (phase,anchor,layer,binding_key),spawns in groups.items():
                reuse = retained.get((bundle['form'],entry['sourceKey']),{})
                if (phase,anchor,layer) in reuse:
                    entry['visuals'].append(deepcopy(reuse[(phase,anchor,layer)]))
                    continue
                if not universal:
                    rendered_coverage.record_empty_sources(entry,spawns,docs,asset_audit)
                rectangle=export.get('backgroundCoverRect')
                detection=entry.get('backgroundDetection')
                fitting=rectangle and detection and detection['kind']=='replacement_background'
                flash_rectangle=export.get('flatFlashCoverRect')
                if flash_rectangle and anchor=='screen':
                    dx,dy=profile.get('screenPlacement',{}).get('sourceOffset',[0,0])
                    flash_rectangle=[flash_rectangle[0]-dx,flash_rectangle[1]-dy,
                                     flash_rectangle[2]-dx,flash_rectangle[3]-dy]
                first,doc=compose(spawns,composition_docs,screen_group_scales=group_scales,
                    background_detection=detection if fitting else None,
                    background_rectangle=rectangle if fitting else None,
                    background_audits=entry.setdefault('backgroundCover',{}) if fitting else None,
                    screen_camera_groups=camera_groups,
                    flash_rectangle=flash_rectangle,
                    flash_audits=entry.setdefault('flatFlashCover',{}) if flash_rectangle else None)
                if not any(doc['frames']):
                    continue
                placement = profile.get('screenPlacement') if anchor == 'screen' else None
                if binding_key == 'viewport_flashes':
                    placement = scene.default_profile(bundle['form'], entry['sourceKey'], {
                        'kind': 'screen_overlay', 'referenceStage': profile.get('screenPlacement', {}).get('referenceStage', [320, 320])})['screenPlacement']
                    placement['runtimeScale'] = export.get('runtimeScale', 1.)
                    if profile.get('screenPlacement', {}).get('fit'):
                        placement['fit'] = profile['screenPlacement']['fit']
                if placement:
                    presentation.validate_screen_placement(placement)
                    # Source coordinates remain visible in spawns. This explicit
                    # profile offsets the source plane before host staging. The
                    # target_stage adapter places all layers together and
                    # frames them with a calibrated native camera.
                    dx,dy = placement['sourceOffset']
                    for frame in doc['frames']:
                        for sprite in frame:
                            sprite['pos'][0] += dx * doc['pixelsPerUnit']
                            sprite['pos'][1] += dy * doc['pixelsPerUnit']
                name='FFBE_FX_'+hashlib.sha256(json.dumps({'doc':doc,'revision':EXPORT_REVISION,'export':export},sort_keys=True).encode()).hexdigest()[:16]
                folder=ASSETS/name
                with file_lock(ASSETS/'.locks'/(name+'.lock')):
                    if not to_ss6.complete_export(folder) or not (folder/'audit.json').is_file():
                        # This final marker covers post-export runtime metadata
                        # too; an interrupted export must not reuse a bare spec.
                        (folder/'audit.json').unlink(missing_ok=True)
                        print('Preparing',entry['name'],anchor,layer,flush=True)
                        # Export each source plane independently, including selected screen layers.
                        spec=to_ss6.convert(doc,str(folder),name,max_units=export.get('maxUnits',900),add_gain=export.get('addGain',.65),scale_mult=export.get('scaleMult',1.6),min_frames=len(doc['frames']),max_cell_size=export.get('maxCellSize',128))
                        if 'runtimeScale' in export or (anchor == 'caster' and 'casterRuntimeScale' in export):
                            # Host battle-design scale is separate from the decoded
                            # FFBE coordinate system and offline source preview.
                            spec['runtimeScale'] = export.get('runtimeScale', export.get('casterRuntimeScale'))
                            # The source root uses SS6's implicit scale of one.
                            # Make that identity explicit for the host multiplier.
                            root_name = spec['model']['parts'][0]['name']
                            setup = next(a for a in spec['animations'] if a['isSetup'])['parts'][root_name]
                            for axis in ('Sclx', 'Scly'):
                                setup.setdefault(axis, [[0, 1.0]])
                            write(folder/'spec.json', spec)
                        if anchor == 'screen' and 'screenRuntimeViewport' in export:
                            # Only screen layers adapt to the wide host viewport;
                            # sprites and caster effects keep their source aspect.
                            spec['runtimeViewport'] = deepcopy(export['screenRuntimeViewport'])
                            root_name = spec['model']['parts'][0]['name']
                            setup = next(a for a in spec['animations'] if a['isSetup'])['parts'][root_name]
                            for axis, value in (('Sclx', 1.0), ('Scly', 1.0), ('Posx', 0.0)):
                                setup.setdefault(axis, [[0, value]])
                            write(folder/'spec.json', spec)
                        write(folder/'audit.json',{'sourceSprites':sum(map(len,doc['frames'])),
                             'slots':len(spec['model']['parts'])-1,'frames':len(doc['frames']),
                             'anchor':anchor,'layer':layer,
                             **({'groupTransforms': doc['groupTransforms'], 'groupTransformCenter': placement['sourceOffset']} if doc.get('groupTransforms') else {})})
                        if make_previews:
                            preview(doc,previews/(name+'.webp'))
                    spec=json.loads((folder/'spec.json').read_text())
                stats=spec.get('conversionAudit',{})
                if stats.get('droppedSpriteFrames') or stats.get('shrunkSpriteFrames'):
                    entry['issues'].append(f'{anchor}/{layer}: {stats.get("droppedSpriteFrames",0)} sprite frames omitted; {stats.get("shrunkSpriteFrames",0)} oversized sprite frames scaled down')
                entry['visuals'].append({'name':name,'asset':f'/Game/Chara/effect/{name}/{name}',
                    'spec':folder.relative_to(ROOT).as_posix(),'frame':first,'frames':len(doc['frames']),
                    'anchor':anchor,'layer':layer,'phase':phase,
                    **({'placement':deepcopy(placement)} if placement else {}),
                    **({'partName':'root'} if profile.get('casterOrigin') == 'feet' else {}),
                    **({'partName':'root','sourceCoordinates':{
                        key:deepcopy(spawns[0]['hostCoordinates'][key]) for key in
                        ('binding','owner','sampleFrame','rectangleMode','offsetsApplied')}} if binding_key and anchor!='screen' else {}),
                    'checksums':{f:digest(folder/f) for f in
                        ['spec.json'] + [page.get('textureFile', 'tex.bgra') for page in spec.get('cellmaps', [spec])]}})
                if placement:
                    entry['issues'].append(
                        'Native target stage uses a calibrated perspective camera; viewport parity across targets and aspect ratios is not established'
                        if placement['mode'] == 'target_stage' else
                        'Source screen coordinates are fitted to the native camera viewport and field of view; source aspect and depth adaptation still require native visual review'
                        if placement['mode'] == 'camera_plane' else
                        'Source screen layer uses a frozen actor-relative plane; viewport/camera parity is not established')
                if anchor=='each_target' and entry['targetType']!='Single':
                    entry['issues'].append('Area damage is intact; sprite impacts currently attach to the first selected target')
            entry['issues'] += [f'{file}: {issue}' for file in sorted({s['file'] for s in entry['spawns']}) if file in asset_audit for issue in asset_audit[file]['issues']]
            entry['issues'] += [f'Sound {s["cueId"]}: {entry_omissions[str(s["cueId"])]}' for s in entry['sounds'] if str(s['cueId']) in entry_omissions]
            entry['issues']=sorted(set(entry['issues']))
            entry['status']='partial' if entry['issues'] else 'prepared'
        destination = Path(manifest_out) if manifest_out is not None else presentation.BUNDLES/(bundle['form']+'.json')
        merge_source = destination if destination.is_file() else presentation.BUNDLES/(bundle['form']+'.json')
        published = bundle
        if merge_existing and merge_source.is_file():
            previous=json.loads(merge_source.read_text(encoding='utf-8'))
            if str(previous.get('form'))!=bundle['form'] or previous.get('schema')!=presentation.VERSION:
                raise ValueError('Cannot merge a different form or incompatible presentation')
            # The reusable manifest retains earlier moves. This preparation's
            # report describes only its own work, avoiding quadratic copies of
            # every earlier move in a large unit's per-move reports.
            published={**bundle,'moves':{**previous['moves'],**bundle['moves']}}
        write(destination,published)
    audit={'schema':presentation.VERSION,'decoderFidelity':'Approximate particle simulation; game validation pending',
           'forms':prepared,'assets':asset_audit,'soundOmissions':shipped_sound_omissions,
           'soundOmissionsByMove':sound_omissions_by_move}
    write(WORK/'report.json',audit)
    if make_previews:
        report(audit)
    print(json.dumps({'forms':len(forms),'moves':sum(len(b['moves']) for b in prepared.values()),
                      'uniqueParticleFiles':len(asset_audit),'soundCues':len(all_sounds),'omittedSounds':shipped_sound_omissions}),flush=True)
    return audit


def report(audit):
    cards=[]
    for form,bundle in audit['forms'].items():
        for entry in bundle['moves'].values():
            esc=html.escape
            pics=''.join(f'<figure>'+ (f'<img loading="lazy" src="previews/{v["name"]}.webp">' if (WORK/'previews'/(v['name']+'.webp')).is_file() else '<p>Existing prepared visual; no fresh preview in this run.</p>')+f'<figcaption>{v["anchor"]} · {"front" if v["layer"]==1 else "back"} · frame {v["frame"]}</figcaption></figure>' for v in entry['visuals'])
            notes=''.join(f'<li>{esc(n)}</li>' for n in entry['issues']) or '<li>No detected reference or export gaps.</li>'
            cards.append(f'<article data-status="{entry["status"]}"><h2>{esc(entry["name"])}</h2><small>{form} · {esc(entry["sourceKey"])}</small><p>{len(entry["sounds"])} sound events · {len(entry["spawns"])} particle spawns · {entry["status"]}</p><div class="previews">{pics}</div><details><summary>Conversion notes ({len(entry["issues"])})</summary><ul>{notes}</ul></details></article>')
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><title>FFBE effect conversion</title>
<style>body{font:16px/1.5 system-ui;background:#10131b;color:#e5eaf5;max-width:1300px;margin:40px auto;padding:0 24px}h1{font-size:36px;margin-bottom:10px}p{color:#b7c4d9}input,select{background:#202839;color:inherit;border:1px solid #53617c;border-radius:6px;padding:12px;margin:8px 10px 20px 0}input{min-width:320px}article{background:#191f2c;border:1px solid #303c51;border-radius:12px;padding:24px;margin:18px 0}h2{margin:0}small,figcaption{color:#a6b7d1}.previews{display:flex;flex-wrap:wrap;gap:15px}figure{margin:8px 0}img{width:240px;height:240px;border-radius:8px}details{margin-top:16px}li{margin:6px 0}summary{cursor:pointer}a{color:#96c7ff}[hidden]{display:none}</style>
<h1>FFBE · sound & particle conversion</h1><p>Prepared from the selected original effects. Previews show the offline decoder; FFR lighting and camera placement need an in-game comparison. Conversion limits and any reference-specific placement are listed for each move.</p>
<p>Battle review: check sound volume and sync, target placement, front/back layering, effect size and cleanup on repeated casts. Area mechanics still hit all enemies; first-target visual limitations are flagged per move.</p>
<input id="search" placeholder="Search moves, IDs or conversion notes" aria-label="Search moves"><select id="status" aria-label="Conversion status"><option value="">All conversions</option><option value="prepared">Prepared without detected gaps</option><option value="partial">Partial conversions</option></select><a href="report.json">Full inventory</a><main>'''+''.join(cards)+'''</main><script>function filter(){const q=document.querySelector('#search').value.toLowerCase(),s=document.querySelector('#status').value;document.querySelectorAll('article').forEach(a=>a.hidden=!a.textContent.toLowerCase().includes(q)||(s&&a.dataset.status!==s));}document.querySelector('#search').oninput=filter;document.querySelector('#status').onchange=filter;</script></html>'''
    (WORK/'index.html').write_text(page,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('forms',nargs='+')
    parser.add_argument('--move', action='append', help='Prepare only these exact source keys')
    parser.add_argument('--profile', type=Path, help='Explicit reference reconstruction settings')
    parser.add_argument('--work', type=Path, help='Isolated preparation report/cache directory')
    args=parser.parse_args()
    if args.work: WORK=args.work.resolve()
    prepare(args.forms,args.move,json.loads(args.profile.read_text(encoding='utf-8')) if args.profile else None)
