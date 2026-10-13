-- Observe native W Action selecting two copies of the production Fire body.
-- All mutations affect only the protected process's fresh initial unit data.
local M={}
local phase=0
local baseline
local begun,begin_count,settled={},0,nil
local current_caster,cancelled
local function emit(text) print('[FFRMultiCommandDriver] '..text..'\n') end
local function values(list)
    local result={}
    for _,v in ipairs(list) do result[#result+1]=type(v)=='number' and v or v:get() end
    table.sort(result);return result
end
local function contains(list,id)
    for _,v in ipairs(list) do if v==id then return true end end
    return false
end
local function stack(vm,label)
    local current=vm:GetCurrentStackData()
    emit(string.format('stack phase=%s count=%d state=%d key=%d index=%d parent=%d next=%d node=%d',
        label,vm.CommandStack:GetArrayNum(),current.BtlCmdState,current.ActionKey.ID,current.Index,
        current.ParentIndex,current.NextIndex,vm.CommandNode.ActionKey.ID))
    emit(string.format('stack_mp phase=%s getter=%d raw=%d display=%d',label,current_caster:GetMagicPoint(),
        current_caster:GetRawParameter().MagicPoint,current_caster:GetDisplayMagicPoint()))
end
function M.setup()
    assert(FFRBattleProbeMultiCommand and FFRBattleProbeProtectedSaves)
    require('fire_driver').setup()
    local data=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataUnit')
    local units={};data:GetSaveDataUnitParameterList(units)
    assert(#units==8,'multi-command fixture requires fresh initial units')
    local before={};data:GetMasterActiveSkillList(before,1001);before=values(before)
    assert(not contains(before,400710),'fixture W Action already mastered')
    data:AddMasterSkill(1001,400710)
    assert(not contains(before,900010),'fixture Fire already mastered')
    data:AddMasterSkill(1001,900010)
    local after={};data:GetMasterActiveSkillList(after,1001);after=values(after)
    emit('master_grants unit=1001 before='..table.concat(before,',')..' after='..table.concat(after,','))
    assert(#after==#before+2 and contains(after,400710) and contains(after,900010),'native active master grant failed')
    local pre,post=RegisterHook('/Script/mucha.CPP_VM_BtlLibra:HandleSkillBegin',function(_,remote)
        local value=remote:get()
        if value.SkillId==900010 then
            local payload=value:GetFullName()
            if not begun[payload] then
                begun[payload]=true;begin_count=begin_count+1
                emit(string.format('cast_begin ordinal=%d unique=%d payload=%s',begin_count,value.actionUnitUniqueId,payload))
            end
        end
    end)
    assert(type(pre)=='number' and type(post)=='number','multi-command cast observer failed')
end
function M.tick(units)
    if phase==4 or #units~=2 then return end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    local p=battle:GetBattleUnitParameterByUnitId(1001,false)
    local enemy=battle:GetBattleUnitParameterByUnitId(5,false)
    if not p or not p:IsValid() or not enemy or not enemy:IsValid() then return end
    current_caster=p
    assert(p:GetHitPoint()>0 and enemy:GetHitPoint()>0,'multi-command fixture lost a combatant')
    local turn=p:GetActionCountInBattle()
    emit(string.format('sample phase=%d turn=%d hp=%d mp=%d lb=%d enemy_hp=%d fire=%d',phase,turn,
        p:GetHitPoint(),p:GetMagicPoint(),p:GetLimitBurstPoint(),enemy:GetHitPoint(),enemy:GetResistanceToElement(1)))
    emit(string.format('mp phase=%d getter=%d raw=%d display=%d',phase,p:GetMagicPoint(),p:GetRawParameter().MagicPoint,p:GetDisplayMagicPoint()))
    if phase==3 then
        assert(begin_count<=2,'extra Fire cast began')
        if begin_count==2 and p:GetMagicPoint()==baseline.mp-8 and enemy:GetHitPoint()<baseline.enemy and enemy:GetResistanceToElement(1)==1 then
            if settled~=enemy:GetHitPoint() then settled=enemy:GetHitPoint();return end
            emit(string.format('result before_mp=%d after_mp=%d before_enemy=%d after_enemy=%d before_lb=%d after_lb=%d turn=%d',
                baseline.mp,p:GetMagicPoint(),baseline.enemy,enemy:GetHitPoint(),baseline.lb,p:GetLimitBurstPoint(),turn))
            phase=4;emit('multicommand_complete')
            print('[FFRConvertedDriver] converted_observation_complete\n')
        end
        return
    end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {};local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local unique=managers[1]:GetCurrentActionUnitUniqueId()
    if unique<0 or battle:GetUnitIdByUniqueId(unique)~=1001 then return end
    local vm=models[1]
    assert(turn==1,'selection advanced owner opportunity')
    if phase==5 then
        assert(vm.CommandStack:GetArrayNum()==0 and p:GetMagicPoint()==baseline.mp
            and p:GetRawParameter().MagicPoint==baseline.mp and p:GetDisplayMagicPoint()==baseline.mp
            and p:GetHitPoint()==baseline.hp and p:GetLimitBurstPoint()==baseline.lb
            and enemy:GetHitPoint()==baseline.enemy and begin_count==0,'cancellation retained cost or executed a cast')
        assert(vm:CanActivateAction({Category=1,ID=900010}),'cancelled command remained unavailable')
        emit(string.format('cancel_verified turn=%d mp=%d hp=%d lb=%d enemy_hp=%d',turn,p:GetMagicPoint(),p:GetHitPoint(),p:GetLimitBurstPoint(),enemy:GetHitPoint()))
        phase=0;return
    end
    if phase==0 then
        local active={};p:GetActiveSkillListWithVision(active);active=values(active)
        emit('native_owned unit=1001 skills='..table.concat(active,','))
        assert(contains(active,400710) and contains(active,900010),'mastered skills absent from native ownership')
        baseline={mp=p:GetMagicPoint(),enemy=enemy:GetHitPoint(),lb=p:GetLimitBurstPoint(),hp=p:GetHitPoint()}
        assert(vm:CanActivateAction({Category=1,ID=400710}),'native W Action unavailable')
        stack(vm,'before_root');vm:DecideActionKey({Category=1,ID=400710});stack(vm,'after_root')
        phase=1
    elseif phase==1 or phase==2 then
        assert(p:GetMagicPoint()==baseline.mp-4*(phase-1) and enemy:GetHitPoint()==baseline.enemy and begin_count==0,'unexpected native selection cost or execution')
        if phase==2 and FFRBattleProbeMultiCancel and not cancelled then
            stack(vm,'before_cancel')
            local count=0
            while vm.CommandStack:GetArrayNum()>0 do
                local before=vm.CommandStack:GetArrayNum()
                count=count+1;assert(count<=6,'cancellation exceeded stack bound')
                vm:CancelCommand();stack(vm,'cancel_'..count)
                assert(vm.CommandStack:GetArrayNum()<before,'cancellation did not shrink native stack')
            end
            cancelled=true;phase=5;return
        end
        local key={Category=1,ID=900010}
        assert(vm:CanActivateAction(key),'native Fire selection unavailable')
        local target=battle:GetDefaultSkillTargetUnitUniqueId(unique,key.ID)
        assert(target>=0 and battle:GetUnitIdByUniqueId(target)==5,'multi-command target mismatch')
        emit(string.format('select ordinal=%d unique=%d skill=%d target=%d turn=%d',phase,unique,key.ID,target,turn))
        vm:DecideActionKey(key);stack(vm,'selected_'..phase)
        vm:DecideTarget({target},false);stack(vm,'targeted_'..phase)
        phase=phase+1
    end
end
return M
