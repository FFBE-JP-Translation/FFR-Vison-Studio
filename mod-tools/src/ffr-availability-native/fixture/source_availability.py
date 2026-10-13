"""Build a disposable payload with its original held availability contract.

This module is deliberately outside the production importer. The generated
package is usable only with the protected source-availability test runner.
"""
from copy import deepcopy
from dataclasses import replace
import json
from ability_converter import commands
from ability_converter.availability import plan
from ability_converter.compiler import TableWriter


def lua_literal(value):
    if isinstance(value,bool): return 'true' if value else 'false'
    if type(value) is int: return str(value)
    if isinstance(value,str):
        assert all(32<=ord(c)<127 for c in value),'Fixture contract strings must be printable ASCII'
        return json.dumps(value)
    if isinstance(value,list):return '{'+','.join(lua_literal(v) for v in value)+'}'
    if isinstance(value,dict):
        return '{'+','.join('['+lua_literal(k)+']='+lua_literal(v) for k,v in sorted(value.items()))+'}'
    raise TypeError(type(value))


def source_profile(record,catalog,directory):
    original=commands.profile(record,catalog)
    contract=plan(record,catalog)
    assert not original['supported'] and not contract['playable']
    assert contract['validation']['rulesDecoded'] and contract['validation']['payloadReady']
    # Keep the ordinary source and nested plan impossible to export through
    # the production table writer, even while cooking this explicit fixture.
    assert not commands.from_snapshot(original['snapshot'])['supported']
    try: TableWriter(commands.converter().native).add(contract['payload'])
    except ValueError:pass
    else:raise AssertionError('Held availability payload unexpectedly exported')
    data=deepcopy(record.data)
    for gate in contract['gates']:
        index=gate['component']
        assert data['effects_raw'][index]==gate['raw']
        if gate['kind']=='charges':
            assert gate['appliesToSelf']
            data['effects_raw'][index]=[0,3,0,[]]
        else:data['effects_raw'][index]=[0,3,71,[int(gate['childId']),1]]
    payload=commands.profile(replace(record,data=data),catalog)
    assert payload['supported'] and not payload['issues']
    assert payload['set']['TargetType']=='Self','The source fixture resolves self-target support only'
    assert payload['conversion']['native']==contract['payload']['native']
    assert payload['conversion']['costs']==contract['payload']['costs']
    assert payload['timeline']['hitFrames']==contract['timeline']['hitFrames']
    (directory/'availability-plan.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    runtime={'key':record.key,'gates':contract['gates'],'target':0}
    script='-- Generated from the retained original FFBE availability plan.\nreturn '+lua_literal(runtime)+'\n'
    (directory/'source_contract.lua').write_text(script,encoding='utf8')
    return original,payload,contract
