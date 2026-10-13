"""Step-one presentation: shared cast audio and camera, without particle media."""
from copy import deepcopy
from pathlib import Path
import json

import ffbe_audio
import ffbe_attack_director as director

ROOT = Path(__file__).resolve().parents[1]


def entry(unit, skill, prepared=None):
    source = (skill.get('conversionSource') or {}).get('root', 'FFR/ability/445020')
    kind = 'lb' if skill.get('resonance') else source.split('/')[1]
    # Existing prepared banks carry the ability activation cue. No particle
    # dependency is required to give a previously unprepared move its camera.
    bank = (prepared or {}).get('audioBank')
    if kind == 'ability':
        if bank is None or 100 not in ffbe_audio.bank_info(str(ROOT / bank), (ROOT / bank).stat().st_mtime_ns)['cues']:
            for manifest in sorted((ROOT / 'data/ffbe/presentation').glob('*.json')):
                doc = json.loads(manifest.read_text(encoding='utf-8'))
                candidate = next((e.get('audioBank') for e in doc.get('moves', {}).values()
                                  if e.get('cast', {}).get('bank') == 'SE'), None)
                if candidate and (ROOT / candidate).is_file():
                    bank = candidate
                    break
        if not bank:
            raise ValueError('Step-one camera needs the shared FFBE ability cast sound')
    else:
        bank = str(ffbe_audio.system_bank(skill) or '')
        if not bank:
            raise ValueError('Step-one camera needs the FFBE System sound bank')
    settings = director.resolve(str(unit['ffbe']['id']), source, {})
    settings.update(hideLbNonParticipants=False)
    result = {'sourceKey': source, 'audioBank': bank, 'sounds': [], 'visuals': [],
              '_hostVisionUnitId': unit['id'], '_hostResonance': kind == 'lb',
              '_hostTargetCamera': unit.get('presentationStep') == 'target_camera',
              'reconstructionProfile': {'attackDirector': settings}}
    if prepared and prepared.get('motionType') is not None:
        result['motionType'] = prepared['motionType']
    if kind != 'lb':
        result['cast'] = {'bank': 'SE' if kind == 'ability' else 'System',
                          'cueName': ffbe_audio.ABILITY_OPENING_CUE if kind == 'ability' else ffbe_audio.MAGIC_OPENING_CUE,
                          'frame': 1 if kind == 'ability' else 0,
                          'durationFrames': 10 if kind == 'ability' else 30,
                          'motion': 'command' if kind == 'ability' else 'magic_idle'}
    return result


def lb_source(source):
    result = deepcopy(source)
    # Separate the common opening from travel so cast focus is visible before
    # following the actor. Source action/hit frames keep their relative timing.
    result['opening'] = {'durationFrames': 30 + (25 if result.get('moveType') == 1 else 0)}
    result['castBeforeMoveFrames'] = 30
    result['sounds'] = []
    return result


def sequence_id(skill_id, recipe):
    return 2_000_000 + skill_id * 2 if recipe.get('fullKitSequence') else skill_id + 1
