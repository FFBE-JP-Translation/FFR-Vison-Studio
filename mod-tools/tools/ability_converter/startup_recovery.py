"""Bind reviewed passive MP/resonance recovery to FFR's battle-start event."""


def valid(native, spec):
    binding = spec.get('resourceBinding') or {}
    row = spec['set']
    params = row['ParamList']
    if binding.get('activation') != 'battle_start_once': return False
    donor = native.passives[native.passive_ids[1049]]
    bundles = [b for b in donor['effectBundleList'] if b['effectId'] >= 0]
    if (native.inventory['enums']['eSkillTiming']['BeginBattle'] != 10 or donor['bBattleOnly'] is not False
            or len(bundles) != 1 or bundles[0]['passiveSkillAddTiming'] != 'BeginBattle'):
        raise ValueError('Native battle-start registration contract changed')
    if (spec.get('passiveTiming') != 'BeginBattle' or row['EffectType'] != 'ParameterVariation'
            or params[1] not in (2, 4) or params[0] <= 0
            or row['applyTiming'] != 'AddEffect' or row['proceedTiming'] != 'AddEffect'
            or row['effectEndActionNum'] != 1 or binding.get('owner') != 'equipping_main_cast'
            or spec['target']['shape'] != 'Self' or spec['target']['relation'] != 'Friendlies'
            or spec.get('children') or spec.get('randomChoices')):
        raise ValueError('Startup recovery must apply once to its equipping main-cast owner')
    return True
