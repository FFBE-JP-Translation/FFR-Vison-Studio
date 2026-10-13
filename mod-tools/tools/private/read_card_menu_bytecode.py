import json,sys
from pathlib import Path
b=json.loads(Path(sys.argv[1] if len(sys.argv)>1 else 'build/vision-cards/equipped-bp.json').read_text(encoding='utf-8-sig'))
def obj(i):
    return b['Imports'][-i-1]['ObjectName'] if i<0 else b['Exports'][i-1]['ObjectName'] if i else 'null'
def expr(v):
    if isinstance(v,list):return [expr(x) for x in v]
    if not isinstance(v,dict):return v
    t=v.get('$type','').split('.')[-1].split(',')[0]
    if t=='KismetPropertyPointer':return '.'.join(v['New']['Path'])
    if t in ('EX_InstanceVariable','EX_LocalVariable','EX_LocalOutVariable'):return t+':'+expr(v['Variable'])
    if t=='EX_ObjectConst':return 'Object:'+obj(v['Value'])
    if t=='EX_FinalFunction':return {'Call':obj(v['StackNode']),'Args':expr(v['Parameters'])}
    return {t:{k:expr(x) for k,x in v.items() if k not in ('$type','Offset','PropertyType','RValuePointer')}}
for e in b['Exports']:
    if e['ObjectName'] in ('BP_OnDecideInput','InputDecide','BP_GetInputTargetWidget','HandleClickEquipped','SetAsInputTarget'):
        print(e['ObjectName'],json.dumps(expr(e['ScriptBytecode']),indent=2))
