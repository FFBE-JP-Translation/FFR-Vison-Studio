"""Native group recipients for owner-executed automatic support children."""
from copy import deepcopy
from .native import CONDITION

EVIDENCE = {'supportSkillId':503550,'factory':'0x144f7bdd0','bundleIterator':'0x144f7bd10',
    'groupCollector':'0x144faff30','sideInversion':'0x14522e4a0',
    'replay':'build/abilities/native-hit-evidence/automatic-recipients-replay.json','runtime':'not_run'}
CHANGE = ('Automatic child support retains separate Self, all-living-allies and all-living-enemies '
    'effect bundles. Groups are selected relative to the acting owner when the child executes, '
    'using native death, destroyed-unit and vision filtering; no extra command selection is required.')


def contract(native, child):
    effects=(child.get('native') or {}).get('effects') or []
    if not effects:raise ValueError('Automatic child has no support effects')
    groups=False;plan=[]
    def visit(effect, path, inherited=None):
        nonlocal groups
        t=effect['target'];shape=t['shape'];relation=t['relation']
        target={'shape':shape,'relation':relation,'state':t['state']}
        if (shape not in ('Self','Group') or relation not in ('Friendlies','Enemies')
                or (shape=='Self' and relation!='Friendlies') or t['state']!='Alive'
                or t.get('ignoreSelf') or t.get('eitherSide') or effect.get('targetBinding')):
            raise ValueError('Automatic child support requires Self or unfiltered living-group recipients')
        if inherited is not None and target!=inherited:
            raise ValueError('Automatic child wrapper must retain its inherited recipients')
        if effect.get('skillElement') or effect.get('tagAttack'):
            raise ValueError('Automatic child contains a separate application binding')
        groups|=shape=='Group'
        plan.append({'path':path,'target':target,'activeTiming':effect.get('activeTiming','AfterDamageCalculation')})
        for key in ('children','randomChoices'):
            for index,nested in enumerate(effect.get(key,[])):visit(nested,[*path,key,index],target)
    for index,effect in enumerate(effects):visit(effect,[index])
    if not groups:return None
    donor=native.skills[native.skill_ids[503550]]
    bundles=[b for b in donor['effectBundleList'] if b['effectId']>=0]
    if (donor['Cost']!=0 or donor['magnification']!=0 or donor['skillEffectType']!='None'
            or donor['TargetType']!='Self' or not donor['isParallelExecutable']
            or not donor['isAliveOnly'] or donor['isAvailableWhenDead']
            or donor['playSequencerId']!=-1 or donor['sequencerIdWhenTargetFriendlies']!=-1
            or [(b['effectId'],b['TargetType'],b['targetRelation']) for b in bundles]!=[
                (19049,'Self','Friendlies'),(16115,'Group','Enemies'),(16113,'Group','Enemies'),
                (16114,'Group','Enemies'),(1373,'Group','Enemies')]
            or any(b['activeSkillAddTiming']!='AfterDamageCalculation' or b['conditionData']!=CONDITION for b in bundles)):
        raise ValueError('Native automatic group-support template changed')
    return {'actor':'grant_recipient','commandTarget':'Self','bundles':plan,'nativeEvidence':deepcopy(EVIDENCE)}
