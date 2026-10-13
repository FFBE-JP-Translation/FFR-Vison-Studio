"""Compile the saved shared-effect review; no ability-name matching."""
from copy import deepcopy
import json

CLARIFICATIONS = [
    {'effect': 'active:73', 'message': "if it's the rouletter ability, stick with notes. you can drop any no oped effect with 0 linked abilities",
     'resolution': 'The single observed record is GL_2024/enemy/140140 Roulette. Its random FFR skill selector note overrides skip.'},
]
OVERRIDES = {
    'active:8': 'Immediate scaled HP recovery. Song/dance locks are removed; unsupported consecutive-use scaling is disclosed separately.',
    'active:9': 'Ordinary physical/magic damage from structured skill type, using the source fraction as its base multiplier; no percentage-HP damage.',
    'active:13': 'Immediate ordinary damage using parameter 5 and structured skill type; delay removed.',
    'active:16': 'Immediate fixed HP recovery; no inventory item consumption.',
    'active:17': 'Immediate fixed MP recovery; no inventory item consumption.',
    'active:20': 'Clone both effects of native Fina Magic Boost command 400660, including its next-magic MP-cost increase.',
    'active:21': 'Normal physical damage at the decoded multiplier; ignore-DEF bonus removed.',
    'active:22': 'Ordinary 1x physical base damage; race check and race-only bonus removed.',
    'active:23': 'Ordinary 1x magical base damage; race check and race-only bonus removed.',
    'active:27': 'Native Reraise graph where decoded; otherwise ordinary Raise with the decoded HP percentage.',
    'active:30': 'One immediate fixed MP recovery (source base / 2); unsupported stat scaling disclosed separately.',
    'active:31': 'Native Entrust transfers the donor main-cast resonance gauge to the selected recipient.',
    'active:56': 'Song becomes one immediate scaled HP recovery without channel lock.',
    'active:57': 'Song becomes one immediate fixed MP recovery without channel lock; unsupported scaling disclosed separately.',
    'active:73': 'Requested random FFR skill selector. Remains unresolved until a native arbitrary-skill selection/execution binding exists; never silently skip.',
    'active:74': 'Ordinary 1x magic attack as an explicit review-stage replacement; original opcode parameters have no decoded magnitude.',
    'active:1003': 'Immediate percentage resonance recovery for main-cast recipients, using parameter 1.',
    'active:130': 'Remove cooldown and initial-turn restrictions; expand the referenced move, retaining compatible child components.',
    'active:131': 'Damage song becomes one immediate magic attack using modifier times duration. Unsupported consecutive-use scaling disclosed separately.',
    'passive:32': 'One MP recovery at battle start (source percentage capped at 5%), never a repeating turn trigger.',
    'passive:33': 'One main-cast resonance recovery at battle start (crystal units / 100 capped at 5%), never a repeating turn trigger.',
    'field:3': 'Decode HP and MP recovery independently. MP becomes immediate; field recipient/removal binding remains required.',
    'field:4': 'Decode independent resources and retain recovery candidates while reporting unsupported resources and field bindings.',
}


def compile_rules(folder):
    review = json.loads((folder/'review-snapshot.json').read_text(encoding='utf-8'))
    catalog = json.loads((folder/'catalog-snapshot.json').read_text(encoding='utf-8'))
    rules = {}
    for effect in catalog['effects']:
        key = effect['key']; decision = deepcopy(review['decisions'][key])
        targets = decision['targets']
        if key == 'active:73':
            targets = ['other']
        unused_noop = not effect['recordCount'] and targets == ['skip']
        mode = 'drop_unused' if unused_noop else 'drop' if targets == ['skip'] else 'override' if key in OVERRIDES else 'unresolved' if 'other' in targets else 'decoder'
        rules[key] = {'key':key, 'label':effect['label'], 'occurrences':effect['occurrences'],
            'recordCount':effect['recordCount'], 'savedDecision':decision, 'effectiveTargets':targets,
            'mode':mode, 'implementation':OVERRIDES.get(key, effect.get('suggestedIntent','')),
            'proposal':effect.get('proposal',{}), 'defaultTargets':catalog['defaults'][key]['targets']}
    assert len(rules) == len(review['decisions']) == 346
    return {'schemaVersion':'ffbe-ffr-reviewed-rules/1', 'catalogId':catalog['catalogId'],
        'savedRevision':review['revision'], 'clarifications':CLARIFICATIONS,
        'rules':rules, 'policies':[
            'All source records and all raw components receive a report entry.',
            'Keep independent compatible components and disclose every omitted component/subpart.',
            'Cooldown is removed. Missing references/cycles are reported.',
            'LB refill restores main-cast resonance; self means the equipping main-cast actor.',
            'MP/LB periodic recovery is converted to one immediate application; passive recovery runs once at battle start.',
            'Preserve unknown costs and non-cooldown availability gates as blocking issues.',
            'Good means a structurally checked draft with useful native mechanics. Gameplay and final unit integration remain untested.',
            'Unchanged dropdown defaults name a behavior family, not a restriction to one native row type; parameter-specific native alternatives remain visible.',
        ]}
