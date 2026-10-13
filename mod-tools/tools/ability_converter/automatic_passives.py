"""Permanent owner-triggered private automatic support actions."""
from copy import deepcopy

from .delayed_actions import child_contract, self_target, templates

PARAMS = [0,-1,1000,5000,0,0,1,0,-1,-1,0,0,0,-1,-1]
START_PARAMS = [0,-1,1000,5000,1,0,1,0,-1,-1,0,0,0,-1,-1]
EVIDENCE = {'grantEffectId':1071,'privateSkillTemplate':210240,'targetPolicyId':1000,
    'actor':'grant_recipient','dispatcher':'0x145224d20','application':'0x1450ff9a0',
    'beginTurn':'0x144fb1d80','revival':'0x14512fa80','removal':'0x14523c9e0',
    'runtime':'not_run'}


def decode(code, params):
    from .adapters import integer
    if code not in (66,103,104):
        raise ValueError('Automatic passive trigger has no native binding')
    if len(params) not in ((2,3) if code==66 else (3,)):
        raise ValueError('Automatic passive has an unsupported source layout')
    child=integer(params[0],'Automatic passive child ID',1,2147483646)
    chance=integer(params[1],'Automatic passive chance',0,100) if code==66 else 100
    controls=[integer(p,'Automatic passive source control') for p in params[2 if code==66 else 1:]]
    semantic={'kind':'automatic_passive','mode':'automatic_passive','childId':str(child),
        'sourceTrigger':{66:'every_turn',103:'battle_start',104:'on_revival'}[code],
        'nativeTrigger':{66:'BeginTurn',103:'BeginBattle',104:'Revival'}[code],'chance':chance,
        'sourceControls':controls,'nativeBinding':deepcopy(EVIDENCE)}
    semantic['nativeBinding']=evidence(semantic)
    issues=['Nonzero automatic-passive controls require verified source semantics'] if any(controls) else []
    return semantic,issues


def convert(context):
    semantic,issues=decode(context.code,context.p)
    context.r['semantic']=semantic
    context.r['dependencies']=[{'id':semantic['childId'],'kind':'skill','relation':'automatic',
        'condition':{k:semantic[k] for k in ('sourceTrigger','nativeTrigger','chance','sourceControls')}}]
    context.r['issues'].extend(issues)


def settings(native, semantic):
    templates(native)
    if any(native.inventory['enums']['eSkillTiming'][k]!=v for k,v in (('BeginTurn',7),('Revival',51))):
        raise ValueError('Native automatic passive trigger enumeration changed')
    row=native.effect(1071,PARAMS,turns=-1,unremovable=True,status='None')['set']
    row.update(applyTiming=semantic['nativeTrigger'],activationProbability=semantic['chance'])
    if semantic['nativeTrigger']=='BeginBattle':
        donor=native.passives[native.passive_ids[1049]]
        bundles=[b for b in donor['effectBundleList'] if b['effectId']>=0]
        if (native.inventory['enums']['eSkillTiming']['BeginBattle']!=10 or donor['bBattleOnly'] is not False
                or len(bundles)!=1 or bundles[0]['effectId']!=54201 or bundles[0]['TargetType']!='Self'
                or bundles[0]['passiveSkillAddTiming']!='BeginBattle'
                or bundles[0]['conditionData']['Condition']!='None'):
            raise ValueError('Native battle-start passive template changed')
        row.update(ParamList=list(START_PARAMS),applyTiming='AddEffect',proceedTiming='AddEffect',
                   effectEndActionNum=1,isUnremovable=False)
    return row


def evidence(semantic):
    if semantic['nativeTrigger']!='BeginBattle':return deepcopy(EVIDENCE)
    return {**deepcopy(EVIDENCE),'passiveTemplate':1049,'beginBattle':'0x144fa2ebd',
        'passiveDispatcher':'0x145224360','registration':'0x145223540',
        'replay':'build/abilities/native-hit-evidence/battle-start-replay.json'}


def bind(compiler, record, component, stack):
    try:
        if record.namespace!='passive' or compiler.resolver is None:
            raise ValueError('Automatic passive requires an equipping owner and a source catalog')
        child_record=compiler.resolver.resolve(record.provenance(),component['dependencies'][0])
        child=compiler.convert(child_record,stack)
        component['expanded']=child
        component['dependencies'][0]['resolved']=child_record.key
        child_contract(compiler.native,child,label='Automatic passive')
        semantic=component['semantic']
        semantic['nativeBinding']=evidence(semantic)
        row={'template':1071,'set':settings(compiler.native,semantic),'component':component['index'],
            'target':deepcopy(component['target']),
            'automaticPassive':{'source':record.key,'component':component['index'],'code':component['code'],
                'parameters':deepcopy(component['params']),'child':deepcopy(child),'nativeEvidence':evidence(semantic)}}
        if component['code']==103:row['passiveTiming']='BeginBattle'
        from .automatic_recipients import contract, CHANGE as RECIPIENT_CHANGE
        recipients=contract(compiler.native,child)
        if recipients:row['automaticPassive']['recipientBinding']=recipients
        component['effects']=[row]
        trigger={66:'at each native turn start',103:'at native battle start',104:'after the owner is revived'}[component['code']]
        grant='a temporary battle-start grant' if component['code']==103 else 'a permanent passive'
        lifetime='The startup grant expires immediately after its activation attempt.' if component['code']==103 else 'The grant follows native permanent-passive removal rules.'
        component['changes'].extend([*child['changes'],
            f'Automatic {"group" if recipients else "self"} support uses {grant} that invokes its private child {trigger}. '
            'The child costs no additional resources and has no command-menu entry. '
            +lifetime])
        if recipients:component['changes'].append(RECIPIENT_CHANGE)
        component['status']='replaced' if child['status']=='replaced' else 'adapted'
        semantic.update(child=child_record.key,actor='equipping_actor',additionalCost=0)
    except (ValueError,TypeError,KeyError,IndexError) as ex:
        component['status']='blocked';component['issues'].append(str(ex))


def validate(native, spec, depth=0):
    if depth>64:raise ValueError('Automatic passive graph exceeds supported depth')
    if binding:=spec.get('automaticPassive'):
        from .compiler import TableWriter
        semantic,issues=decode(binding['code'],binding['parameters'])
        child=binding['child'];child_contract(native,child,label='Automatic passive')
        from .automatic_recipients import contract
        if binding.get('recipientBinding')!=contract(native,child):
            raise ValueError('Automatic child requires its complete recipient binding')
        if (issues or binding['nativeEvidence']!=evidence(semantic) or child['source']['id']!=semantic['childId']
                or spec['template']!=1071 or spec['set']!=settings(native,semantic)
                or spec.get('passiveTiming','SpawnUnit')!=('BeginBattle' if binding['code']==103 else 'SpawnUnit')
                or not self_target(spec['target']) or spec.get('children') or spec.get('randomChoices')):
            raise ValueError('Automatic passive requires its complete private trigger contract')
        TableWriter(native).add(child)
    elif (spec['set']['EffectType']=='AutomaticSkill' and not spec.get('delayedAction')
            and (spec['set']['applyTiming'] in ('BeginTurn','Revival') or spec.get('passiveTiming')=='BeginBattle')):
        raise ValueError('Automatic passive cannot omit its private child binding')
    for child in [*spec.get('children',[]),*spec.get('randomChoices',[])]:validate(native,child,depth+1)


def emit(writer, spec):
    from .delayed_actions import emit as emit_private
    return emit_private(writer,spec,binding_key='automaticPassive',prefix='automatic-passive')


def coverage(spec):
    codes=set()
    if binding:=spec.get('automaticPassive'):
        codes.update(('automatic-passive:code:'+str(binding['code']),
            'automatic-passive:trigger:'+('BeginBattle' if binding['code']==103 else spec['set']['applyTiming']),
            'automatic-passive:chance:'+str(spec['set']['activationProbability']),
            'automatic-passive:layout:'+str(len(binding['parameters']))))
        for child in binding['child']['native']['effects']:
            codes.add('automatic-passive:child-effect:'+child['set']['EffectType'])
            codes.add('automatic-passive:child-target:'+child['target']['shape']+':'+child['target']['relation'])
    for child in [*spec.get('children',[]),*spec.get('randomChoices',[])]:codes.update(coverage(child))
    return codes
