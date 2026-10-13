"""Native resistance bundles beside damage, with an explicit battle-turn clock."""
from copy import deepcopy
import hashlib
import json

EVIDENCE = {
    'kind':'native_execution_and_instruction_replay', 'skillId':1900010, 'effectId':190001000,
    'source':'JP_2024/magic/20010', 'templateId':1022,
    'binarySha256':'e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad',
    'bundleIterator':'0x144f7bd10', 'recipientFactory':'0x144f7bdd0',
    'battleTurnAccessor':'0x144f52720', 'durationClock':'native_shared_battle_turn',
    'phaseComparisonRuns':['20260910_214414_857','20260910_214344_265'],
    'expiryRun':'20260910_215302_350',
    'phaseReportSha256':'d0fa4a468fbb245be58b385cf841c88da34c18903c3ebd589744724b2ff0ee8a',
    'phaseEvidenceReport':'native-hit-evidence/resistance-phase-at-binding.json',
    'expiryReportSha256':'689fed84377eb4d623de9ffd7596fd725aeaadfb363c462065fff581d5ed6676',
    'expiryEvidenceReport':'native-hit-evidence/resistance-expiry-at-binding.json',
    'recipientReplaySha256':'a7df6c17995a5a7259053aef1efa8933c8cb348019b56601a22ab799edf6284b',
    'scope':'After-damage native resistance class; Fire cast/expiry plus Self/Group phase and recipient replay. Other element/category values require native row evidence.',
}
TEMPLATE_SHA256='1150cb85b19ca63671842ab625e0aab24079e9ef63c58b17726c16d61cc74735'
CHANGE="Effect durations use FFR's shared battle-turn clock; individual actor actions are not full effect turns."


def evidence(native, effect, variation):
    row=effect['set']
    if variation!='Decrease' or row['EffectType']!='AddElementResistance' or effect['activeTiming']!='AfterDamageCalculation':
        return None
    enums=native.inventory['enums']
    if (enums['eSkillEffectType']['AddElementResistance']!=18 or enums['eSkillTiming']['BeginTurn']!=7
            or enums['eActiveSkillEffectTiming']['AfterDamageCalculation']!=1):
        raise ValueError('Native resistance phase or battle-turn timing changed')
    template=json.dumps(native.effects[1022],sort_keys=True,separators=(',',':')).encode()
    if hashlib.sha256(template).hexdigest()!=TEMPLATE_SHA256:
        raise ValueError('Native resistance effect template changed')
    params=row['ParamList']
    if len(params)!=15 or any(type(v) is not int for v in params):
        raise ValueError('Resistance phase requires complete integral native parameters')
    element,category=params[:2]
    if not any(r['ParamList'][:2]==[element,category] for r in native.types['AddElementResistance']['effectRows']):
        raise ValueError('Resistance phase requires native element/category evidence')
    turns=row['effectEndActionNum']
    if type(turns) is not int or not 1<=turns<=native.general['effectMaxLifeTime']:
        raise ValueError('Resistance phase requires a bounded native battle-turn lifetime')
    if type(row['addProbability']) is not int or not 0<=row['addProbability']<=100:
        raise ValueError('Resistance phase requires an integral native application chance')
    expected=native.effect(1022,[element,category],turns=turns,chance=row['addProbability'],
                           unremovable=row['isUnremovable'])['set']
    if effect['template']!=1022 or row!=expected or effect.get('children') or effect.get('randomChoices'):
        raise ValueError('Resistance phase requires its complete native continuous-effect contract')
    return deepcopy(EVIDENCE)
