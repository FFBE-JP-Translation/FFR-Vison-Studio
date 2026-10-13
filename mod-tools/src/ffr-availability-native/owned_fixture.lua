-- Native ownership-driven fixture host. No roster IDs select an owner here.
-- This proves stable equipping actors; late grants, actor replacement and
-- multi-action selections still require a broader lifecycle binding.
local Probe=require('availability_probe')
local Engine=require('availability')
local Host=require('native_host')
local contract=require('source_contract')
local SKILL=900010
assert(contract.target==0 and #contract.gates==1 and contract.gates[1].kind=='limited')
local COMMAND,GATE=contract.key,contract.gates[1].key
local engine=Engine.new({{key=COMMAND,gates=contract.gates}})
local owners,pending,seen={},{},{}
local battle,failed
local generation,owner_serial,selection,queries=0,0,0,0
local previous={}
local function emit(event,fields)
    fields=fields or {};fields.event=event
    print('[FFRAvailabilityNative] '..Probe.json(fields)..'\n')
end
local function read_owner(unique)
    local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    local parameter=library:GetBattleUnitParameterWithVision(unique,false)
    assert(parameter and parameter:IsValid(),'source parameter missing')
    local actor=parameter.m_pVisionOwner
    if not actor or not actor:IsValid() then actor=parameter.m_pOwnerBtlUnit end
    assert(actor and actor:IsValid(),'equipping actor missing')
    local p=actor.m_pUnitParameter
    assert(p and p:IsValid(),'equipping parameter missing')
    local values,skills,owned={},{},false
    p:GetActiveSkillListWithVision(values)
    for _,value in ipairs(values) do
        local id=type(value)=='number' and value or value:get()
        assert(type(id)=='number' and id==math.floor(id),'invalid native skill ID')
        skills[#skills+1]=id;if id==SKILL then owned=true end
    end
    assert(#skills<=2048,'native loadout exceeds fixture bound');table.sort(skills)
    return {actor=actor:GetAddress(),name=actor:GetFullName(),parameter=p:GetAddress(),unitId=p:GetUnitId(),
        uniqueId=unique,ordinal=p:GetActionCountInBattle()+1,skills=skills,owned=owned,object=p,
        visionId=p:GetEquipmentId(4,0),relation=p:GetRelation()}
end
local function same_owner(record,native)
    return record and record.actor==native.actor and record.name==native.name and record.parameter==native.parameter
end
local function used(record)
    local state=record and engine.owners[record.owner]
    local data=state and state.gates[GATE]
    return data and data.used or -1
end
local function sync_loadout(record,native,origin)
    if not FFRAvailabilityFixtureLoadout then return end
    assert(same_owner(record,native),'loadout changed actor identity')
    local before=record.owned
    local ok,reason=engine:sync_loadout(battle,record.owner,native.owned and {COMMAND} or {})
    assert(ok,reason);record.owned=native.owned
    if before~=native.owned then
        emit('owned_loadout',{owner=record.owner,actor=native.actor,parameter=native.parameter,unitId=native.unitId,
            uniqueId=native.uniqueId,before=before,owned=native.owned,used=used(record),visionId=native.visionId,
            turn=engine.owners[record.owner].turn,origin=origin,skills=native.skills})
    end
end
local function guarded(path,callback)
    local pre,post=RegisterHook('/Script/mucha.'..path,function(...)
        local ok,reason=pcall(callback,...)
        if not ok then failed=true;emit('owned_binding_failed',{path=path,reason=tostring(reason)}) end
    end)
    assert(type(pre)=='number' and type(post)=='number','owner hook registration failed')
end
if FFRAvailabilityFixtureLife then
    guarded('CPP_BtlDelEventUnit:OnExecuteUpdateDeadState',function(_,remote)
        if not battle then return end
        local native=read_owner(remote:get().UniqueID);local record=owners[native.actor]
        if not record then return end
        assert(same_owner(record,native),'death event changed owner identity')
        local state=engine.owners[record.owner];local before=state.alive
        local alive=not native.object:IsDead()
        local ok,reason=engine:set_alive(battle,record.owner,alive);assert(ok,reason)
        local available,why=engine:query(battle,record.owner,COMMAND,true)
        emit('owned_life',{owner=record.owner,actor=native.actor,parameter=native.parameter,unitId=native.unitId,
            uniqueId=native.uniqueId,aliveBefore=before,alive=alive,hp=native.object:GetHitPoint(),
            turn=state.turn,used=state.gates[GATE].used,available=available,reason=why,payload=remote:get():GetFullName()})
    end)
end
if FFRAvailabilityFixtureReset then
    local ending
    local function protect(callback)
        return function(...)
            local ok,reason=pcall(callback,...)
            if not ok then failed=true;emit('owned_binding_failed',{path='battle end',reason=tostring(reason)}) end
        end
    end
    local pre,post=RegisterHook('/Script/mucha.CPP_UI_BattleSubsystem:HandleEndBtl',protect(function(context,remote)
        local subsystem=context:get()
        assert(battle and not ending and subsystem.bDuringBattle,'unexpected native battle end')
        ending={battle=battle,subsystem=subsystem:GetAddress(),payload=remote:get():GetFullName()}
        emit('owned_end_before',{battle=battle,subsystem=ending.subsystem,payload=ending.payload,during=true})
    end),protect(function(context,remote)
        local subsystem=context:get()
        assert(ending and ending.battle==battle and ending.subsystem==subsystem:GetAddress()
            and ending.payload==remote:get():GetFullName() and not subsystem.bDuringBattle,'native battle end did not clear its state')
        assert(not next(pending),'battle ended with unresolved source selection')
        previous={}
        for _,record in pairs(owners) do
            local state=engine.owners[record.owner]
            previous[#previous+1]={battle=battle,owner=record.owner,used=state.gates[GATE].used,turn=state.turn}
        end
        assert(#previous==2,'battle end lost an owned actor')
        local ok,reason=engine:end_battle(battle);assert(ok,reason)
        assert(not engine.active and not next(engine.owners),'canonical end retained owners')
        emit('owned_end_after',{battle=battle,subsystem=ending.subsystem,payload=ending.payload,during=false,
            ownersCleared=#previous,active=engine.active})
        for _,old in ipairs(previous) do
            local allowed,why=engine:query(old.battle,old.owner,COMMAND,true)
            assert(not allowed and why=='stale_battle','old battle query survived end')
            emit('owned_stale_query',{phase='after_end',battle=old.battle,owner=old.owner,used=old.used,
                turn=old.turn,decision=allowed,reason=why})
        end
        owners={};pending={};seen={};battle=nil;ending=nil
    end))
    assert(type(pre)=='number' and type(post)=='number','native end observer registration failed')
end
function FFRAvailabilityOnNativeBattleBegin(subsystem,before,after,caller)
    local ok,reason=pcall(function()
        assert(not before and after and not battle and (generation==0 or FFRAvailabilityFixtureReset),'unexpected battle lifecycle transition')
        generation=generation+1;battle='owned-battle:'..generation
        local started,why=engine:begin_battle(battle);assert(started,why)
        emit('owned_battle',{battle=battle,subsystem=subsystem,before=before,after=after,callerRva=caller})
        for _,old in ipairs(previous) do
            local allowed,why=engine:query(old.battle,old.owner,COMMAND,true)
            assert(not allowed and why=='stale_battle','old battle query survived new battle')
            emit('owned_stale_query',{phase='after_begin',battle=old.battle,owner=old.owner,used=old.used,
                turn=old.turn,decision=allowed,reason=why,currentBattle=battle})
        end
    end)
    if not ok then failed=true;emit('owned_binding_failed',{path='native begin',reason=tostring(reason)}) end
end
guarded('CPP_UI_BattleSubsystem:HandleBeginTurn',function(_,remote)
    assert(battle,'turn before native battle start')
    local native=read_owner(remote:get().UniqueID)
    local record=owners[native.actor]
    if not record and not native.owned and not (FFRAvailabilityFixtureLoadout and native.relation==1) then return end
    if not record then
        assert(native.ordinal==1,'newly owned command requires late-grant lifecycle support')
        owner_serial=owner_serial+1
        record={actor=native.actor,name=native.name,parameter=native.parameter,unitId=native.unitId,
            owner=battle..':owner:'..owner_serial,owned=native.owned}
        local ok,reason=engine:register_owner(battle,record.owner,native.owned and {COMMAND} or {});assert(ok,reason)
        owners[native.actor]=record
        emit('owned_registered',{owner=record.owner,actor=record.actor,parameter=record.parameter,
            unitId=record.unitId,uniqueId=native.uniqueId,skills=native.skills,command=COMMAND,visionId=native.visionId,owned=native.owned})
    end
    assert(same_owner(record,native) and not pending[native.actor],'owner identity changed or prior selection unresolved')
    sync_loadout(record,native,'turn')
    local ok,reason=engine:begin_turn(battle,record.owner,native.ordinal);assert(ok,reason)
    emit('owned_turn',{owner=record.owner,actor=record.actor,unitId=record.unitId,uniqueId=native.uniqueId,
        ordinal=native.ordinal,owned=native.owned,used=used(record),visionId=native.visionId})
end)
guarded('CPP_BtlDelEventCmd:OnExecuteDecideCommand',function(_,remote)
    local value=remote:get();local entries={};local managed=false
    value.cmdDecideDataList:ForEach(function(_,v)
        local entry=v:get();entries[#entries+1]=entry;if entry.actionId==SKILL then managed=true end
    end)
    if not managed then return end
    assert(#entries==1 and not value.isNotConsume,'multiple/automatic selection requires another binding')
    local entry=entries[1];local native=read_owner(entry.actionUnitUniqueId);local record=owners[native.actor]
    assert(not entry.isUseItem and native.owned and same_owner(record,native),'unowned or mismatched source selection')
    sync_loadout(record,native,'selection')
    local targets={};entry.targetUnitUniqueIdList:ForEach(function(_,v) targets[#targets+1]=v:get() end)
    assert(#targets==1 and targets[1]==entry.actionUnitUniqueId,'source support requires its actual self target')
    local payload=value:GetFullName()
    assert(not seen[payload] and not pending[native.actor] and selection<8192,'duplicate or unresolved command selection')
    seen[payload]=true;selection=selection+1
    local context={battle=battle,owner=record.owner,cast=battle..':cast:'..selection,
        group=battle..':selection:'..selection,uniqueId=entry.actionUnitUniqueId,record=record}
    pending[native.actor]=context
    emit('owned_selection',{owner=record.owner,actor=native.actor,unitId=native.unitId,uniqueId=native.uniqueId,
        cast=context.cast,group=context.group,payload=payload,target=targets[1],turn=engine.owners[record.owner].turn})
end)
local guard,ids=Host.bind(engine,{[SKILL]=COMMAND},function(context)
    local selected=pending[context.actor]
    if failed or not selected or context.job~=context.rootJob or context.actionCount~=1 or context.targetCount~=1 then return nil end
    local native=read_owner(selected.uniqueId)
    if not native.owned or not same_owner(selected.record,native) then return nil end
    sync_loadout(selected.record,native,'execution')
    return selected
end)
function FFRAvailabilityOnNativeQuery(unique,skill,native_allowed,caller)
    local allowed,reason=false,'native_unavailable'
    local native,record
    if (native_allowed or FFRAvailabilityFixtureLoadout) and not failed and battle then
        local ok,value=pcall(read_owner,unique)
        if ok then native=value;record=owners[native.actor] end
        reason=native_allowed and 'unowned_command' or 'native_unavailable'
        if native and same_owner(record,native) then sync_loadout(record,native,'query') end
        if native and native.owned and same_owner(record,native) and skill==SKILL then
            allowed,reason=engine:query(battle,record.owner,COMMAND,native_allowed)
        end
    end
    queries=queries+1
    if queries<=2000 then
        emit('owned_menu_query',{uniqueId=unique,skillId=skill,nativeAllowed=native_allowed,decision=allowed,
            reason=reason,callerRva=caller,owner=record and record.owner or 'unbound',
            actor=native and native.actor or 0,unitId=native and native.unitId or -1,
            owned=native and native.owned or false,used=used(record),
            turn=record and engine.owners[record.owner].turn or 0})
    elseif queries==2001 then emit('owned_query_capacity',{limit=2000}) end
    return allowed
end
local attach=FFRAvailabilityNativeAttach
function FFRAvailabilityNativeAttach(enforce,commands)
    assert(enforce==false and commands=='','unexpected owner fixture attachment')
    local begun,why=FFRBattleFixtureObserveBegin();assert(begun,why)
    local query_ok,query_why=require('query_fixture').bind(SKILL);assert(query_ok,query_why)
    local observe=FFRAvailabilityOnNativeGuard
    function FFRAvailabilityOnNativeGuard(job,actor,root,skill,index,actions,targets,native)
        observe(job,actor,root,skill,index,actions,targets,native)
        local context=pending[actor];local record=context and context.record
        local used=record and engine.owners[record.owner].gates[GATE].used or -1
        local ok,allowed,reason=pcall(guard,job,actor,root,skill,index,actions,targets,native)
        if not ok then failed=true;reason=tostring(allowed);allowed=false;emit('owned_binding_failed',{path='native guard',reason=reason}) end
        emit('owned_authorization',{actor=actor,owner=record and record.owner or 'unbound',unitId=record and record.unitId or -1,
            job=job,cast=context and context.cast or 'missing',nativeAllowed=native,decision=allowed,reason=reason or 'unresolved_context',
            usedBefore=used,usedAfter=record and engine.owners[record.owner].gates[GATE].used or -1})
        if context then engine:finish_group(context.battle,context.owner,context.group) end
        pending[actor]=nil;return allowed
    end
    local ok,reason=attach(true,table.concat(ids,','))
    emit('owned_enforcement_attached',{allowed=ok,reason=reason,command=COMMAND,gate=GATE,skillId=SKILL})
    return ok,reason
end
