-- Actual native equipment APIs change Vision-granted skill membership while
-- the same two actors remain in battle. No command list override is used.
local M={}
local records,active={},nil
local context_prepared=false
local function emit(text) print('[FFRLoadoutDriver] '..text..'\n') end
function M.setup()
    assert(FFRBattleProbeVisionSource and FFRBattleProbeLoadoutSource)
    require('owned_driver').setup()
end
local function owns(p)
    local list={};p:GetActiveSkillListWithVision(list)
    for _,v in ipairs(list) do if (type(v)=='number' and v or v:get())==900010 then return true end end
    return false
end
function M.tick(units)
    local parameters={}
    for _,actor in ipairs(units) do
        local p=actor.m_pUnitParameter
        if p and p:IsValid() then
            local id=p:GetUnitId()
            if id==1001 or id==1002 then parameters[id]=p
            elseif id==5 then assert(p:GetHitPoint()==200,'support damaged enemy') end
        end
    end
    if not parameters[1001] or not parameters[1002] then return end
    for id,p in pairs(parameters) do
        assert(p:GetHitPoint()>0,'fixture owner died')
        records[id]=records[id] or {mp=p:GetMagicPoint()}
        assert(p:GetMagicPoint()==records[id].mp,'source spent MP')
        emit(string.format('sample unit=%d turn=%d hp=%d mp=%d lb=%d vision=%d owned=%s',id,
            p:GetActionCountInBattle(),p:GetHitPoint(),p:GetMagicPoint(),p:GetLimitBurstPoint(),p:GetEquipmentId(4,0),tostring(owns(p))))
    end
    if active then
        local p=parameters[active.unit];local lb=p:GetLimitBurstPoint()
        if lb==active.before+20 then
            emit(string.format('source_result unit=%d turn=%d before_lb=%d after_lb=%d mp=%d',active.unit,
                p:GetActionCountInBattle(),active.before,lb,p:GetMagicPoint()))
            records[active.unit].cast=true;active=nil
        else assert(lb==active.before,'unexpected source gauge result');return end
    end
    if records[1001].finished and records[1002].finished then
        emit('loadout_complete owners=2 source_casts=2')
        print('[FFRConvertedDriver] converted_observation_complete\n');return
    end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {};local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    local unique=managers[1]:GetCurrentActionUnitUniqueId();if unique<0 then return end
    local id=battle:GetUnitIdByUniqueId(unique);local p=parameters[id];local record=records[id]
    if not p or record.finished then return end
    local turn=p:GetActionCountInBattle();if record.last_turn==turn then return end
    local vm=models[1];local source={Category=1,ID=900010};local action=source
    if turn==1 then
        assert(p:GetEquipmentId(4,0)==-1 and not owns(p) and not vm:CanActivateAction(source),'source was owned before grant')
        emit(string.format('initial_unowned unit=%d unique=%d turn=%d',id,unique,turn))
        action={Category=1,ID=400010}
    elseif turn==2 then
        local vision=id==1001 and 13017 or 13045
        assert(p:GetEquipmentId(4,0)==-1 and not owns(p) and not vm:CanActivateAction(source),'late grant precondition changed')
        local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Unit')
        local map=StaticFindObject('/Script/mucha.Default__CPP_BFL_Map')
        if not context_prepared then
            local maps=FindAllOf('CPP_MapManager') or {};local uis=FindAllOf('CPP_UI_BattleSubsystem') or {}
            assert(#maps==1 and #uis==1 and uis[1].bDuringBattle and not map:IsDuringEncount(),'unexpected initial debug battle context')
            local ok,reason=FFRBattleFixtureEquipmentContext(maps[1]:GetAddress(),uis[1]:GetAddress());assert(ok,reason)
            assert(map:IsDuringEncount(),'native equipment context did not change')
            context_prepared=true;emit('debug_equipment_context_prepared')
        end
        local selected=library:GetPlayableUnitParameterObj(id)
        emit(string.format('equipment_context unit=%d during_encount=%s native_parameter=%d battle_parameter=%d native_vision=%d',
            id,tostring(map:IsDuringEncount()),selected and selected:IsValid() and selected:GetAddress() or 0,
            p:GetAddress(),selected and selected:IsValid() and selected:GetEquipmentId(4,0) or -999))
        assert(selected and selected:IsValid() and selected:GetAddress()==p:GetAddress(),'equipment API selected another actor parameter')
        library:SetEquipmentId(id,vision,0)
        local data=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataUnit')
        emit(string.format('equipment_set_result unit=%d initial_vision=%d battle_vision=%d owned=%s',id,data:GetEquipmentId(id,4,0),p:GetEquipmentId(4,0),tostring(owns(p))))
        assert(p:GetEquipmentId(4,0)==vision and owns(p),'native in-battle equipment grant failed')
        assert(vm:CanActivateAction(source),'newly granted source was unavailable')
        emit(string.format('granted unit=%d unique=%d turn=%d vision=%d actor=%d parameter=%d',id,unique,turn,vision,p.m_pOwnerBtlUnit:GetAddress(),p:GetAddress()))
        active={unit=id,before=p:GetLimitBurstPoint()};assert(active.before<=80,'source gauge lacks headroom')
    elseif turn==3 then
        local vision=id==1001 and 13017 or 13045
        assert(record.cast and not vm:CanActivateAction(source),'source failed to spend its first use')
        local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Unit')
        assert(library:UnequipmentId(id,vision),'native unequip failed')
        assert(p:GetEquipmentId(4,0)==-1 and not owns(p) and not vm:CanActivateAction(source),'removed source remained available')
        emit(string.format('removed unit=%d unique=%d turn=%d vision=-1',id,unique,turn))
        library:SetEquipmentId(id,vision,0)
        assert(p:GetEquipmentId(4,0)==vision and owns(p),'native regrant failed')
        assert(not vm:CanActivateAction(source),'regrant restored a spent use')
        emit(string.format('regranted_exhausted unit=%d unique=%d turn=%d vision=%d',id,unique,turn,vision))
        record.finished=true;action={Category=1,ID=400010}
    else error('unexpected loadout fixture owner opportunity') end
    assert(vm:CanActivateAction(action),'control command unavailable')
    record.last_turn=turn
    emit(string.format('command unit=%d unique=%d turn=%d skill=%d',id,unique,turn,action.ID))
    vm:DecideActionKey(action);vm:DecideTarget({unique},false)
end
return M
