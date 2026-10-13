"""Countdown-triggered private automatic support actions."""
from copy import deepcopy
import hashlib
import json
from .native import CONDITION

PARAMS = [0,-1,1000,5000,1,0,1,3,1,-1,0,0,0,-1,-1]
EVIDENCE = {'grantEffectId':1071,'privateSkillTemplate':210240,'targetPolicyId':1000,
    'actor':'grant_recipient','battleClock':'0x144fb1d80','dispatcher':'0x145224d20',
    'countdown':'0x145101804','application':'0x1450ff9a0','expiry':'0x14523c130',
    'runtime':'not_run'}
CHANGE = ('Delayed self support uses one private automatic action at the requested native BeginTurn, '
    'then expires whether its activation chance succeeds or fails. The child applies its converted '
    'support effects together, costs no additional resources and receives no command-menu entry. '
    'Native turn clocks and automatic-effect removal rules apply.')


def templates(native):
    from .reraise import templates as private_template
    row=native.effects[1071]
    expected={'EffectType':'AutomaticSkill','ParamList':[0,501620,1002,5000,1,0,1,3,1,-1,0,0,0,-1,-1],
        'applyTiming':'ActionBegin','proceedTiming':'ActionEnd','effectEndActionNum':3,
        'statusCondition':'Doom','isExecutingReaction':False,'isUnremovable':False,
        'addProbability':100,'activationProbability':100,'activationCondition':CONDITION}
    if any(row[k]!=v for k,v in expected.items()):
        raise ValueError('Native automatic countdown template changed')
    if native.inventory['enums']['eSkillTiming']['BeginTurn']!=7:
        raise ValueError('Native automatic turn clock changed')
    if native.target_policies[1000] != {'ID':1000,'targetRelation':'Friendlies','isAlive':True,
            'skillTargetCondition':'Self','skillTargetConditionParamList':[-1,-1,-1]}:
        raise ValueError('Native automatic support target policy changed')
    return private_template(native)


def decode(params, maximum):
    from .adapters import integer
    if len(params) not in (5,6):
        raise ValueError('Delayed actions require five source parameters and an optional effect identifier')
    child=integer(params[0],'Delayed child ID',1,2147483647)
    control=integer(params[1],'Delayed source control')
    turns=integer(params[2],'Delayed turn count',1,2147483647)
    chance=integer(params[3],'Delayed activation chance',0,100)
    dual=integer(params[4],'Delayed dual-wield control',0,1)
    identifier=integer(params[5],'Delayed effect identifier',0,2147483647) if len(params)==6 else None
    semantic={'kind':'delayed_action','mode':'delayed','childId':str(child),'delayTurns':turns,
        'chance':chance,'sourceControl':control,'dualWieldControl':dual,'sourceEffectIdentifier':identifier,
        'nativeBinding':deepcopy(EVIDENCE)}
    issues=[]
    if control!=0:issues.append('Nonzero delayed-action control requires verified source lifecycle semantics')
    if dual:issues.append('Delayed dual-wield repetition requires equipping-actor binding')
    if turns>maximum:issues.append('Delayed action exceeds the native countdown maximum; it cannot fire early')
    return semantic,issues


def convert(context):
    semantic,issues=decode(context.p,context.native.general['effectMaxLifeTime'])
    context.r['semantic']=semantic
    context.r['dependencies']=[{'id':semantic['childId'],'kind':'skill','relation':'delayed',
        'condition':{k:semantic[k] for k in ('delayTurns','chance','sourceControl','dualWieldControl','sourceEffectIdentifier')}}]
    context.r['issues'].extend(issues)
    if not self_target(context.r['target']):
        context.hold('Delayed actions on other recipients need retained caster and target ownership')


def self_target(target):
    return (target['shape']=='Self' and target['relation']=='Friendlies' and target['state']=='Alive'
            and not target.get('ignoreSelf') and not target.get('eitherSide'))


def child_contract(native, child, label='Delayed'):
    """Only support which can execute without a hit timeline is ready here."""
    from .compiler import source_costs
    n=child.get('native') or {}
    if not child['validation']['tableCompatible']:
        raise ValueError(f'{label} child has blocking issues (see expanded record)')
    if (child['source']['kind'] not in ('ability','magic') or n.get('table')!='Skill/DT_SkillData'
            or any(a for c in child['components'] for a in c['actions']) or n.get('applications')):
        raise ValueError(f'{label} damage and recovery children need automatic timeline and power bindings')
    general=n.get('general') or {}
    if (any(source_costs(child['sourceMetadata']).values()) or child.get('resourceCosts')
            or any(v for k,v in general.items() if k!='equipperActionVisionSkills')):
        raise ValueError(f'{label} child has an additional resource cost or general rule that cannot be omitted')
    from .automatic_recipients import contract
    contract(native,child)
    templates(native)
    return n


def bind(compiler, record, component, stack):
    try:
        if compiler.resolver is None:
            raise ValueError('Delayed child requires a source catalog')
        child_record=compiler.resolver.resolve(record.provenance(),component['dependencies'][0])
        child=compiler.convert(child_record,stack)
        component['expanded']=child
        component['dependencies'][0]['resolved']=child_record.key
        child_contract(compiler.native,child)
        semantic=component['semantic']
        row=compiler.native.effect(1071,PARAMS,turns=semantic['delayTurns'])
        row['set'].update(applyTiming='BeginTurn',statusCondition='None',activationProbability=semantic['chance'])
        row.update(component=component['index'],target=deepcopy(component['target']),
            delayedAction={'source':record.key,'component':component['index'],'parameters':deepcopy(component['params']),
                'child':deepcopy(child),'nativeEvidence':deepcopy(EVIDENCE)})
        from .automatic_recipients import contract, CHANGE as RECIPIENT_CHANGE
        recipients=contract(compiler.native,child)
        if recipients:row['delayedAction']['recipientBinding']=recipients
        component['effects']=[row]
        component['changes'].extend([*child['changes'],CHANGE.replace('Delayed self support','Delayed support') if recipients else CHANGE])
        if recipients:component['changes'].append(RECIPIENT_CHANGE)
        component['status']='replaced' if child['status']=='replaced' else 'adapted'
        component['semantic'].update(child=child_record.key,costOwner=record.key)
    except (ValueError,TypeError,KeyError,IndexError) as ex:
        component['status']='blocked';component['issues'].append(str(ex))


def validate(native, spec, depth=0):
    if depth>64:raise ValueError('Delayed action graph exceeds supported depth')
    if binding:=spec.get('delayedAction'):
        from .compiler import TableWriter
        semantic,issues=decode(binding['parameters'],native.general['effectMaxLifeTime'])
        child=binding['child'];child_contract(native,child)
        from .automatic_recipients import contract
        if binding.get('recipientBinding')!=contract(native,child):
            raise ValueError('Automatic child requires its complete recipient binding')
        expected=native.effect(1071,PARAMS,turns=semantic['delayTurns'])['set']
        expected.update(applyTiming='BeginTurn',statusCondition='None',activationProbability=semantic['chance'])
        if (issues or binding['nativeEvidence']!=EVIDENCE or child['source']['id']!=semantic['childId']
                or spec['template']!=1071 or spec['set']!=expected or not self_target(spec['target'])
                or spec.get('children') or spec.get('randomChoices')):
            raise ValueError('Delayed action requires its complete private countdown contract')
        # Preflight every child contract before allocating anything in the caller.
        # Child graphs are acyclic converted snapshots, bounded by converter expansion.
        TableWriter(native).add(child)
    elif (spec['set']['EffectType']=='AutomaticSkill' and spec['set']['applyTiming']=='BeginTurn'
            and not spec.get('automaticPassive')):
        raise ValueError('Automatic turn actions cannot omit their private child binding')
    for child in [*spec.get('children',[]),*spec.get('randomChoices',[])]:validate(native,child,depth+1)


def emit(writer,spec,*,binding_key='delayedAction',prefix='delayed'):
    binding=spec[binding_key];child=binding['child']
    signature=json.dumps({'set':spec['set'],'binding':binding},sort_keys=True,separators=(',',':'))
    key=prefix+':'+hashlib.sha256(signature.encode()).hexdigest()
    grant_id=writer.allocate('effects',key);child_id=writer.allocate('skills','$'+key)
    if grant_id in writer.emitted:return grant_id
    effects=[]
    for effect in child['native']['effects']:
        effects.append({'effectId':writer.emit_effect(effect),'TargetType':effect['target']['shape'],'targetRelation':effect['target']['relation'],
            'activeSkillAddTiming':effect.get('activeTiming','AfterDamageCalculation'),
            'passiveSkillAddTiming':'None','conditionData':deepcopy(CONDITION)})
    settings=deepcopy(spec['set']);settings['ParamList'][1]=child_id
    writer.native.validate_effect({'template':1071,'set':settings})
    writer.tables.setdefault('Skill/DT_SkillEffectData',{'add':[]})['add'].append({
        'row':f'FFBE_effect_{grant_id}','cloneFrom':writer.native.effect_names[1071],'set':{'ID':grant_id,**settings}})
    row=deepcopy(templates(writer.native))
    row.update(ID=child_id,SortId=child_id,Name=child['name'] or child['source']['id'],Description=writer.description(child),
        effectBundleList=effects,belongCommandList=[],commandIdBelongDebuggingAllSkills=[-1,-1],isMimicEnabled=False,
        isAvailableWhenDead=False,isAliveOnly=True,defaultTargetState='Alive')
    if binding.get('recipientBinding'):
        row.update(TargetType='Self',defaultTargetRelation='Friendlies')
    if child['native'].get('general'):writer.general.add(child_id,child['native']['general'])
    writer.native.validate_skill(row)
    writer.pending_skills.append({'row':f'FFBE_{child_id}','cloneFrom':writer.native.skill_ids[210240],'set':row})
    writer.emitted.add(grant_id)
    return grant_id


def coverage(spec,depth=0):
    codes=set()
    if binding:=spec.get('delayedAction'):
        p=binding['parameters']
        codes.update(('delayed:turns:'+str(p[2]),'delayed:chance:'+str(p[3]),
            'delayed:layout:'+str(len(p)),'delayed:depth:'+str(depth+1)))
        for child in binding['child']['native']['effects']:
            codes.add('delayed:child-effect:'+child['set']['EffectType'])
            codes.add('delayed:child-target:'+child['target']['shape']+':'+child['target']['relation'])
            codes.update(coverage(child,depth+1))
    for child in [*spec.get('children',[]),*spec.get('randomChoices',[])]:codes.update(coverage(child,depth))
    return codes
