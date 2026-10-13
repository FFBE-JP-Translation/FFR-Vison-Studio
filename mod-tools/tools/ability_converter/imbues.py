"""Timed source imbues use native global AddElement effects."""
from copy import deepcopy
from .native import ELEMENT_IDS
from .sources import ELEMENTS
from .multiple_elements import evidence as element_evidence

EVIDENCE = {'templateId':1021,'skillFilter':-1,'elementList':'0x145231510',
    'insertionFunction':'0x145223540','expiryDispatcher':'0x144fbe420','turnTiming':7,'runtime':'not_run'}
CHANGE = ('Elemental imbues add to existing attack elements for their native turn lifetime. '
    'They affect physical and magical damage, with each element applying independently at its source chance. '
    'FFR selects the first non-neutral resistance in native element order.')


def evidence(native):
    element_evidence(native)
    if native.inventory['enums']['eSkillTiming']['BeginTurn'] != 7:
        raise ValueError('Native imbue turn timing changed')
    return deepcopy(EVIDENCE)


def convert(context):
    from .adapters import integer
    p = context.p
    if len(p) not in (9,10):
        raise ValueError('Imbue requires eight element chances and duration, optionally followed by control 1')
    chances = [integer(v,'Imbue element chance',0,100) for v in p[:8]]
    source_turns = context.turn(8)
    control = integer(p[9],'Imbue control') if len(p) == 10 else 1
    maximum = integer(context.native.general['effectMaxLifeTime'],'Native maximum effect lifetime',1)
    turns = min(source_turns,maximum)
    context.r['semantic'] = {'kind':'imbue','chances':chances,'sourceTurns':source_turns,'turns':turns,
        'sourceControl':control,'nativeBinding':evidence(context.native)}
    # Both local formatters decode the first nine slots. The ubiquitous
    # trailing 1 is the ordinary observed layout; do not guess what 0 changes.
    if control != 1:
        context.hold('Nondefault imbue control has no verified source semantics')
        return
    for name,chance in zip(ELEMENTS,chances):
        if not chance:
            continue
        spec = context.effect(1021,[ELEMENT_IDS[name],-1],turns=turns,chance=chance)
        spec['imbue'] = {'element':name,'chance':chance,'turns':turns,'nativeEvidence':evidence(context.native)}
        validate(context.native,spec)
    if any(chances):
        context.change(CHANGE)
        if turns != source_turns:
            context.change(f'Imbue duration is capped from {source_turns} to the native maximum of {maximum} turns.')


def validate(native,spec,depth=0):
    if depth > 64:
        raise ValueError('Imbue effect graph exceeds supported depth')
    row = spec['set']
    if 'imbue' in spec:
        from .adapters import integer
        binding = spec['imbue'];name = binding['element']
        if name not in ELEMENT_IDS or name == 'None':
            raise ValueError('Unknown imbue element')
        chance = integer(binding['chance'],'Imbue chance',1,100)
        turns = integer(binding['turns'],'Imbue duration',1,native.general['effectMaxLifeTime'])
        expected = native.effect(1021,[ELEMENT_IDS[name],-1],turns=turns,chance=chance)['set']
        if (spec['template'] != 1021 or row != expected
                or binding != {'element':name,'chance':chance,'turns':turns,'nativeEvidence':evidence(native)}
                or spec.get('children') or spec.get('randomChoices') or spec.get('skillElement')):
            raise ValueError('Imbue requires its complete global element and turn lifetime contract')
    elif row['EffectType'] == 'AddElement' and row['effectEndActionNum'] > 0 and 'skillElement' not in spec:
        raise ValueError('Timed global elements cannot omit their imbue binding')
    for child in [*spec.get('children',[]),*spec.get('randomChoices',[])]:
        validate(native,child,depth+1)
