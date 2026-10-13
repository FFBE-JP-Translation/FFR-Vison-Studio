-- Fixture-only lifecycle/selection resolver for one ordinary Rain command.
-- Fire uses a synthetic rule; the source mode loads the original decoded
-- FFBE contract alongside its payload. This is not a general loadout resolver.
local Probe=require('availability_probe')
local Engine=require('availability')
local Host=require('native_host')
local SKILL=900010
local contract=FFRAvailabilityFixtureSource and require('source_contract') or
    {key='fixture:limited-fire',target=1,gates={{key='fixture:one-use',kind='limited',owner='equipping_actor',
        maximumUses=1,singleCastWhenDualWielding=true,uniqueSelectionOnMulticast=true}}}
assert(#contract.gates==1 and ((contract.gates[1].kind=='limited' and contract.gates[1].maximumUses==1)
    or (FFRAvailabilityFixtureSource and contract.gates[1].kind=='cooldown')))
local COMMAND,GATE=contract.key,contract.gates[1].key
local engine=Engine.new({{key=COMMAND,gates=contract.gates}})
local battle,owner,actor_address,pending
local generation,selection=0,0
local failed=false
local menu_queries=0
local function emit(event,fields)
    fields=fields or {};fields.event=event
    print('[FFRAvailabilityNative] '..Probe.json(fields)..'\n')
end
local function resolve_owner(unique)
    local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    local p=library:GetBattleUnitParameterWithVision(unique,false)
    assert(p and p:IsValid(),'missing source parameter')
    local actor=p.m_pVisionOwner
    if not actor or not actor:IsValid() then actor=p.m_pOwnerBtlUnit end
    assert(actor and actor:IsValid(),'missing owner actor')
    local parameter=actor.m_pUnitParameter
    assert(parameter and parameter:IsValid(),'missing owner parameter')
    return actor,parameter
end
local function hook(path,callback)
    local pre,post=RegisterHook('/Script/mucha.'..path,function(...)
        local ok,reason=pcall(callback,...)
        if not ok then failed=true;emit('limited_binding_failed',{reason=tostring(reason),path=path}) end
    end)
    assert(type(pre)=='number' and type(post)=='number','fixture hook registration failed')
end
function FFRAvailabilityOnNativeBattleBegin(subsystem,before,after,caller)
    local ok,reason=pcall(function()
    assert(not before and after,'unexpected native battle-start transition')
    generation=generation+1
    assert(generation==1,'fixture supports one battle only')
    battle='fixture-battle:'..generation
    local ok,reason=engine:begin_battle(battle);assert(ok,reason)
    emit('limited_battle',{battle=battle,subsystem=subsystem,before=before,after=after,callerRva=caller})
    end)
    if not ok then failed=true;emit('limited_binding_failed',{reason=tostring(reason),path='native battle begin'}) end
end
hook('CPP_UI_BattleSubsystem:HandleBeginTurn',function(_,remote)
    local unique=remote:get().UniqueID
    local actor,parameter=resolve_owner(unique)
    if parameter:GetUnitId()~=1001 then return end
    assert(battle and not pending,'battle missing or prior command unresolved')
    if not owner then
        actor_address=actor:GetAddress();owner='fixture-owner:'..actor_address
        local ok,reason=engine:register_owner(battle,owner,{COMMAND});assert(ok,reason)
    end
    assert(actor:GetAddress()==actor_address,'ordinary fixture owner changed')
    local ordinal=parameter:GetActionCountInBattle()+1
    local ok,reason=engine:begin_turn(battle,owner,ordinal);assert(ok,reason)
    emit('limited_turn',{battle=battle,owner=owner,actor=actor_address,uniqueId=unique,ordinal=ordinal})
end)
hook('CPP_BtlDelEventCmd:OnExecuteDecideCommand',function(_,remote)
    local value=remote:get();local entries={}
    value.cmdDecideDataList:ForEach(function(_,entry) entries[#entries+1]=entry:get() end)
    local managed=false
    for _,entry in ipairs(entries) do if entry.actionId==SKILL then managed=true end end
    if not managed then return end
    assert(#entries==1 and owner and not pending and not value.isNotConsume,'unsupported fixture command batch')
    local entry=entries[1];local actor,parameter=resolve_owner(entry.actionUnitUniqueId)
    assert(not entry.isUseItem and actor:GetAddress()==actor_address and parameter:GetUnitId()==1001,'fixture command owner mismatch')
    local targets={};entry.targetUnitUniqueIdList:ForEach(function(_,v) targets[#targets+1]=v:get() end)
    assert(#targets==1 and targets[1]==contract.target,'fixture selection target mismatch')
    selection=selection+1
    pending={battle=battle,owner=owner,cast='fixture-cast:'..selection,group='fixture-selection:'..selection}
    emit('limited_selection',{cast=pending.cast,group=pending.group,actor=actor_address,
        turn=engine.owners[owner].turn,payload=value:GetFullName(),target=targets[1]})
end)
local guard,ids=Host.bind(engine,{[SKILL]=COMMAND},function(context)
    if failed or not pending or context.actor~=actor_address or context.job~=context.rootJob
        or context.actionCount~=1 or context.targetCount~=1 then return nil end
    return pending
end)
function FFRAvailabilityOnNativeQuery(unique,skill,native,caller)
    local allowed,reason=false,'unresolved_context'
    if not failed and battle and owner and unique==0 and skill==SKILL then
        -- query is read-only: no reservation, cast token or counter is spent.
        allowed,reason=engine:query(battle,owner,COMMAND,native)
    end
    menu_queries=menu_queries+1
    if menu_queries<=2000 then
        emit('limited_menu_query',{uniqueId=unique,skillId=skill,nativeAllowed=native,decision=allowed,
            reason=reason,callerRva=caller,turn=owner and engine.owners[owner].turn or 0,
            used=owner and engine.owners[owner].gates[GATE].used or 0,
            readyTurn=owner and engine.owners[owner].gates[GATE].readyTurn or 0})
    elseif menu_queries==2001 then emit('limited_menu_capacity',{limit=2000}) end
    return allowed
end
local attach=FFRAvailabilityNativeAttach
function FFRAvailabilityNativeAttach(enforce,commands)
    assert(enforce==false and commands=='','unexpected fixture attach request')
    local begun,begin_reason=FFRBattleFixtureObserveBegin()
    assert(begun,begin_reason)
    if FFRAvailabilityFixtureMenu then
        local query_ok,query_reason=require('query_fixture').bind(SKILL);assert(query_ok,query_reason)
        emit('limited_menu_attached',{allowed=query_ok,reason=query_reason})
    end
    local observe=FFRAvailabilityOnNativeGuard
    function FFRAvailabilityOnNativeGuard(job,actor,root,skill,index,actions,targets,native)
        observe(job,actor,root,skill,index,actions,targets,native)
        local context=pending
        local before=owner and engine.owners[owner].gates[GATE].used or -1
        local ready_before=owner and engine.owners[owner].gates[GATE].readyTurn or -1
        local allowed,reason=guard(job,actor,root,skill,index,actions,targets,native)
        emit('limited_authorization',{cast=context and context.cast or 'missing',actor=actor,job=job,
            nativeAllowed=native,decision=allowed,reason=reason or 'unresolved_context',
            usedBefore=before,usedAfter=owner and engine.owners[owner].gates[GATE].used or -1,
            readyBefore=ready_before,readyAfter=owner and engine.owners[owner].gates[GATE].readyTurn or -1,
            turn=owner and engine.owners[owner].turn or 0})
        if context then engine:finish_group(context.battle,context.owner,context.group) end
        pending=nil
        return allowed
    end
    local ok,reason=attach(true,table.concat(ids,','))
    emit('limited_enforcement_attached',{allowed=ok,reason=reason,skillId=SKILL,mode='enforce',command=COMMAND,gate=GATE})
    return ok,reason
end
