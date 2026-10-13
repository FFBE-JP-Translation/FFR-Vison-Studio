"""Intrinsic tag chaining becomes bounded, skill-filtered native stagger power."""
from copy import deepcopy
from .multiple_elements import TARGET

EVIDENCE = {'templateId':15113,'nativeClass':'CPP_ContFxMulBaseBreakBySkill',
    'initializer':'0x145117090','query':'0x145108e50','collector':'0x145225958',
    'maximumSkillIds':9,'beforeDispatcher':'0x144f7cdd0','expiryDispatcher':'0x144fbe420','runtime':'not_run'}
CHANGE = ('Intrinsic tag chaining becomes 10% additional stagger power per source chain increment, '
    'capped at 20% across overlapping tag sources. It applies only to the tagged damage portions; '
    'damage formulas, elements, targets, hit frames, weights and resource costs remain intact.')


def evidence(native):
    row = native.effects[15113]
    expected = {'EffectType':'MulBaseBreakBySkill','applyTiming':'None','proceedTiming':'None',
        'effectEndActionNum':-1,'ParamList':[150,404080,404110,404060,404070]+[-1]*10,
        'statusCondition':'None','isUnremovable':False,'isExecutingReaction':False,
        'addProbability':100,'activationProbability':100}
    if any(row[k] != v for k,v in expected.items()) or native.inventory['enums']['eSkillTiming']['SkillEnd'] != 18:
        raise ValueError('Native tag stagger template or skill lifetime evidence changed')
    return deepcopy(EVIDENCE)


def convert(context):
    from .adapters import integer
    p = context.p
    if len(p) != 6:
        raise ValueError('Tag attacks require six source parameters')
    listed = isinstance(p[0],list)
    ids = [integer(v,'Tag skill ID',0,2147483647) for v in (p[0] if listed else [p[0]])]
    if not ids or listed and any(v==0 for v in ids):
        raise ValueError('A tag skill list must contain positive skill IDs')
    mode = 'specific_grant' if listed else 'all_attacks_grant' if ids==[0] else 'intrinsic'
    increment = integer(p[1],'Tag chain increment',1,2147483647)
    turns = integer(p[2],'Tag source duration',-1,2147483647)
    control = integer(p[3],'Tag control')
    removable = integer(p[4],'Tag dispel flag',0,1)
    source_effect = integer(p[5],'Tag source effect identifier',0,2147483647)
    context.r['semantic'] = {'kind':'tag_attack','mode':mode,'skillIds':[str(v) for v in ids if v],
        'chainIncrement':increment,'sourceTurns':turns,'sourceControl':control,
        'dispellable':bool(removable),'sourceEffectIdentifier':source_effect,
        'bonusPercent':min(20,10*increment),'nativeBinding':evidence(context.native)}
    context.r['dependencies'] = [{'id':str(v),'kind':'skill','relation':'tag','condition':{'mode':mode}}
                                  for v in dict.fromkeys(ids) if v]
    if control != 1:
        context.hold('Nondefault tag control has no verified source semantics')
    if mode != 'intrinsic':
        context.hold('Timed tag grants require destination skill-set and recipient lifetime bindings')
    elif str(ids[0]) != context.record.id:
        context.hold('Intrinsic tag identity differs from its source ability; external tag grants need separate bindings')
    elif (context.r['target']['shape'] != 'Self' or context.r['target']['relation'] != 'Friendlies'):
        context.hold('Intrinsic tag behavior must belong to the casting actor')
    if not context.r['issues']:
        context.replace('Tag stagger',CHANGE)


def bind_actions(record,components):
    grants = [{'source':record.key,'component':c['index'],'bonusPercent':c['semantic']['bonusPercent']}
              for c in components if c['semantic'].get('kind')=='tag_attack'
              and c['semantic']['mode']=='intrinsic' and not c['issues']]
    if not grants:
        return
    actions = [a for c in components for a in c['actions'] if a['kind']=='damage']
    if not actions:
        raise ValueError('Intrinsic tag behavior needs a decoded damage action')
    for a in actions:
        if a.get('calc',a['damageType']) not in ('Physic','Magic'):
            raise ValueError('Tag stagger requires a physical or magical damage application')
        a['tagGrants'] = deepcopy(a.get('tagGrants',[]))
        for grant in grants:
            if grant not in a['tagGrants']:
                a['tagGrants'].append(deepcopy(grant))


def bonus(action):
    return min(20,sum(g['bonusPercent'] for g in action.get('tagGrants',[])))


def marker(native,actions):
    amounts = {bonus(a) for a in actions}
    if not amounts or amounts=={0}:
        return None
    if len(amounts) != 1 or any(a['kind'] != 'damage' or a.get('calc',a['damageType']) not in ('Physic','Magic') for a in actions):
        raise ValueError('One tag stagger row must share its damage application bonus')
    grants=[]
    for a in actions:
        for g in a['tagGrants']:
            if g not in grants:grants.append(deepcopy(g))
    return {'bonusPercent':next(iter(amounts)),'component':actions[0]['component'],
        'sourceGrants':grants,'nativeEvidence':evidence(native)}


def effects(native,representation):
    groups={}
    for index,job in enumerate([representation,*representation.get('applications',[])]):
        if binding := job.get('tagAttack'):
            groups.setdefault(binding['bonusPercent'],[]).append((index,binding))
    specs=[]
    for amount,jobs in groups.items():
        for start in range(0,len(jobs),9):
            chunk=jobs[start:start+9]
            spec=native.effect(15113,[amount],unremovable=True)
            spec['set'].update(proceedTiming='SkillEnd',effectEndActionNum=1)
            spec.update(component=chunk[0][1]['component'],target=deepcopy(TARGET),activeTiming='BeforeDamageCalculation',
                tagAttack={'applicationIndices':[i for i,_ in chunk],'bonusPercent':amount,'nativeEvidence':evidence(native)})
            specs.append(spec)
    return specs


def finalize(native,result):
    n=result['native']
    n['effects']=effects(native,n)+n['effects']


def validate(native,result):
    n=result['native'];actions=[a for c in result['components'] for a in c['actions']]
    jobs=[n,*n.get('applications',[])]
    specs=[e for e in n['effects'] if 'tagAttack' in e]
    if not specs and not any(j.get('tagAttack') for j in jobs) and not any(a.get('tagGrants') for a in actions):
        return
    if n.get('applications'):
        from .applications import source_owners
        owners=source_owners(result)
        sources=[[actions[i]] for i in owners]
    else:
        sources=[actions]
    for job,source in zip(jobs,sources):
        expected=marker(native,source)
        if (job.get('tagAttack') != expected or expected and
                (job['set']['parameterVariationType'] != 'Decrease' or job['set']['damageCalcType'] not in ('Physic','Magic'))):
            raise ValueError('Tag stagger row differs from its source damage scope')
    if specs != effects(native,n):
        raise ValueError('Tag stagger requires its complete skill-filtered before-damage contract')
    def nested(spec):
        for child in [*spec.get('children',[]),*spec.get('randomChoices',[])]:
            if 'tagAttack' in child:
                raise ValueError('Skill-filtered tag stagger cannot be nested in support effects')
            nested(child)
    for spec in n['effects']:nested(spec)
