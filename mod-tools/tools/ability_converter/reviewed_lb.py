"""Use the selected reviewed LB with the existing FFBE resonance presentation."""
from copy import deepcopy
from . import commands


def resolve(unit, skill):
    import ffbe_lb
    p = commands.from_spec(skill)
    if not p['supported']: return None, p
    if p['conversion']['source']['kind'] != 'lb':
        raise ValueError('A reviewed Resonance must refer to a limit burst')
    try:
        source = deepcopy(ffbe_lb.resolve(unit, skill) or {})
    except (ValueError, KeyError):
        source = {}
    root = p['conversion']['source']
    frames = p['timeline']['hitFrames']
    native = p['conversion']['native']
    weights = (native.get('sequence') or {}).get('hitWeights') or [1.0]
    elements = p['conversion']['presentation'].get('element_inflict') or []
    source.update(lbId=str(root['id']), name=skill.get('en') or p['conversion']['name'],
        hitFrames=frames, hitPercents=[w*100 for w in weights], moveType=p['timeline']['moveType'],
        elements=elements, conversionSource=p['snapshot'], effectPolicy=skill['effectPolicy'])
    p.update(hits=len(frames), lbId=str(root['id']), name=source['name'],
        elements=elements, damageType=p['set']['DamageType'], totalPower=p['set']['magnification'],
        fieldColor=ffbe_lb.element_color(elements), sourceSupported=True,
        target=f"{p['set']['TargetType']} / {p['set']['defaultTargetRelation']}")
    return source, p
