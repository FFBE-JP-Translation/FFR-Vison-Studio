-- Two native actors obtain the source through learning or equipped Visions.
local M={}
local records={};local active_cast;local completed=false
local function emit(text) print('[FFRConvertedDriver] '..text..'\n') end
function M.is_complete() return completed end
function M.reset_battle()
    assert(FFRBattleProbeResetSource and completed and not active_cast,'unexpected owned driver reset')
    records={};completed=false
end
local function command_state(vm)
    local current=vm:GetCurrentStackData()
    return {state=current.BtlCmdState,key=current.ActionKey.ID,index=current.Index,
        stack=vm.CommandStack:GetArrayNum(),node=vm.CommandNode.ActionKey.ID}
end
local function cancel_trace(phase,unit,unique,turn,state,p)
    emit(string.format('owned_cancel phase=%s unit=%d unique=%d turn=%d state=%d key=%d index=%d stack=%d node=%d hp=%d mp=%d lb=%d',
        phase,unit,unique,turn,state.state,state.key,state.index,state.stack,state.node,p:GetHitPoint(),p:GetMagicPoint(),p:GetLimitBurstPoint()))
end
function M.setup()
    assert(FFRBattleProbeOwnedSource and FFRBattleProbeConvertedCase=='limited')
    local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Skill')
    local row=library:GetSkillDataById(900010)
    assert(row.ID==900010 and row.Cost==0 and row.TargetType==0 and row.DamageType==0
        and row.playSequencerId==900011,'unexpected owned source body')
    local membership={}
    for _,value in ipairs(row.belongCommandList) do membership[#membership+1]=type(value)=='number' and value or value:get() end
    assert(#membership==1 and membership[1]==1,'source command membership missing')
    emit('owned_row_verified source=GL_2024/ability/150300')
    if FFRBattleProbeVisionSource then
        assert(FFRBattleProbeProtectedSaves,'Vision fixture needs protected original saves')
        -- Edit only the fresh process's initial data through native APIs.
        -- Gameplay saves are not loaded and no save operation is requested.
        -- Battle construction then consumes these normal equipment entries.
        local inventory=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataInventory')
        local data=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataUnit')
        local list={};data:GetSaveDataUnitParameterList(list)
        emit('vision_initial_units count='..#list)
        assert(#list==8,'Vision fixture requires the initial process unit list')
        local initial={}
        for _,entry in ipairs(list) do
            local value=type(entry)=='table' and entry or entry:get()
            initial[value.UnitId]=true
            emit(string.format('vision_initial_unit unit=%d vision=%d',value.UnitId,value.equipVisionId))
        end
        for _,pair in ipairs({{1001,13017},{1002,13045}}) do
            local unit,vision=pair[1],pair[2]
            assert(initial[unit],'expected ordinary unit identity absent from initial data')
            assert(inventory:FindInventory(vision)==0,'unexpected initial Vision inventory')
            inventory:AddInventory(vision,1)
            assert(inventory:FindInventory(vision)==1,'Vision inventory grant failed')
            emit(string.format('vision_inventory vision=%d before=0 after=1',vision))
            assert(data:GetEquipmentId(unit,4,0)==-1,'unexpected initial unit equipment')
            if FFRBattleProbeLoadoutSource then
                emit(string.format('vision_deferred unit=%d vision=%d equipment=-1',unit,vision))
            else
                data:SetEquipmentId(unit,vision,0)
                assert(data:GetEquipmentId(unit,4,0)==vision,'native initial equipment did not persist')
                emit(string.format('vision_equipped unit=%d vision=%d before=-1 after=%d',unit,vision,vision))
            end
        end
    end
end
function M.tick(units)
    if completed then return end
    local parameters={};local enemy
    for _,unit in ipairs(units) do
        local p=unit.m_pUnitParameter
        if p and p:IsValid() then
            local id=p:GetUnitId()
            if id==1001 or id==1002 then parameters[id]=p elseif id==5 then enemy=p end
        end
    end
    if not enemy or not parameters[1001] or not parameters[1002] then return end
    assert(enemy:GetHitPoint()==200,'support damaged the enemy')
    for _,id in ipairs({1001,1002}) do
        local p=parameters[id];local record=records[id]
        if not record then record={mp=p:GetMagicPoint()};records[id]=record end
        assert(p:GetHitPoint()>0 and p:GetMagicPoint()==record.mp,'owner died or support spent MP')
        emit(string.format('owned_sample unit=%d turn=%d hp=%d mp=%d lb=%d',id,p:GetActionCountInBattle(),p:GetHitPoint(),p:GetMagicPoint(),p:GetLimitBurstPoint()))
    end
    if active_cast then
        local p=parameters[active_cast.unit];local lb=p:GetLimitBurstPoint()
        if lb==active_cast.before+20 then
            records[active_cast.unit].cast=true
            emit(string.format('owned_result unit=%d turn=%d before_lb=%d after_lb=%d mp=%d',active_cast.unit,
                p:GetActionCountInBattle(),active_cast.before,lb,p:GetMagicPoint()))
            active_cast=nil
        else assert(lb==active_cast.before,'unexpected source gauge amount') end
    end
    if not active_cast and records[1001].defended and records[1002].defended then
        completed=true;emit('owned_complete owners=2 source_casts=2 enemy_hp=200')
        if not FFRBattleProbeResetSource then emit('converted_observation_complete') end
        return
    end
    if active_cast then return end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {};local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local unique=managers[1]:GetCurrentActionUnitUniqueId()
    if unique<0 then return end
    local id=battle:GetUnitIdByUniqueId(unique);local p=parameters[id];local record=records[id]
    if not p or not record or record.last_defend==p:GetActionCountInBattle() then return end
    local turn=p:GetActionCountInBattle();local key={Category=1,ID=900010}
    if record.cast and turn<=record.cast_turn then return end
    if not record.cast then
        assert(models[1]:CanActivateAction(key),'owned unused source became unavailable')
        if FFRBattleProbeCancelSource and not record.cancelled then
            local vm=models[1];local before=command_state(vm)
            record.cancel_before={state=before,hp=p:GetHitPoint(),mp=p:GetMagicPoint(),lb=p:GetLimitBurstPoint(),turn=turn,unique=unique}
            cancel_trace('before',id,unique,turn,before,p)
            vm:DecideActionKey(key)
            cancel_trace('selected',id,unique,turn,command_state(vm),p)
            vm:CancelCommand()
            cancel_trace('returned',id,unique,turn,command_state(vm),p)
            record.cancelled=true;return
        end
        if record.cancel_before then
            local before=record.cancel_before;local after=command_state(models[1])
            assert(turn==before.turn and unique==before.unique,'cancelled selection consumed the owner opportunity')
            assert(p:GetHitPoint()==before.hp and p:GetMagicPoint()==before.mp and p:GetLimitBurstPoint()==before.lb,'cancelled source changed resources')
            assert(after.state==before.state.state and after.key==before.state.key and after.stack==before.state.stack,'cancelled command did not restore its native menu state')
            cancel_trace('verified',id,unique,turn,after,p);record.cancel_before=nil
        end
        assert(p:GetLimitBurstPoint()<=80,'owner lacks gauge headroom')
        local target=battle:GetDefaultSkillTargetUnitUniqueId(unique,key.ID)
        assert(target==unique,'owned source did not target its own actor')
        active_cast={unit=id,before=p:GetLimitBurstPoint()}
        record.cast_turn=turn
        emit(string.format('owned_cast_requested unit=%d unique=%d target=%d turn=%d before_lb=%d',id,unique,target,turn,active_cast.before))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({target},false)
        emit('owned_cast_returned unit='..id)
    else
        assert(not models[1]:CanActivateAction(key),'spent owner regained the limited use')
        emit(string.format('owned_menu_blocked unit=%d unique=%d turn=%d',id,unique,turn))
        key.ID=400010;assert(models[1]:CanActivateAction(key),'stock Defend became unavailable')
        record.last_defend=turn;record.defended=true
        emit(string.format('owned_defend_requested unit=%d unique=%d turn=%d',id,unique,turn))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({unique},false)
        emit('owned_defend_returned unit='..id)
    end
end
return M
