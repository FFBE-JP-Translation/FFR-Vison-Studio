-- Temporary converted-Cure test. No runtime authorization rule is enabled.
local M = {}
local phase, granted = 0, false
local before_hp, before_mp
local updates = 0
local skill_id = 900010
local function emit(text) print("[FFRConvertedDriver] "..text.."\n") end

local function observe(parameter, origin)
    if not parameter or not parameter:IsValid() or parameter:GetUnitId()~=1001 then return end
    local hp,mp=parameter:GetHitPoint(),parameter:GetMagicPoint()
    emit(string.format("parameter origin=%s hp=%d mp=%d turn=%d",origin,hp,mp,parameter:GetActionCountInBattle()))
    if phase==2 and hp>before_hp and hp<=parameter:GetMaxHitPoint() and mp==before_mp-4 then
        phase=3
        emit(string.format("healing_observed before_hp=%d after_hp=%d before_mp=%d after_mp=%d",before_hp,hp,before_mp,mp))
        emit("converted_observation_complete")
    end
end

function M.setup()
    assert(FFRBattleProbeConvertedAbility==skill_id,"unexpected converted fixture ID")
    local library=StaticFindObject("/Script/mucha.Default__CPP_BFL_Skill")
    assert(library and library:IsValid(),"skill library unavailable")
    local row=library:GetSkillDataById(skill_id)
    for _,field in ipairs({"ID","Cost","magnification","hitCount","playSequencerId","parameterVariationType","DamageType","TargetType","defaultTargetRelation"}) do
        emit("loaded_row "..field.."="..tostring(row[field]))
    end
    assert(row.ID==skill_id and row.Cost==4 and row.magnification==62 and row.hitCount==1
        and row.playSequencerId==skill_id+1 and row.parameterVariationType==0
        and row.DamageType==2 and row.TargetType==1 and row.defaultTargetRelation==1,
        "loaded converted Cure row differs from the cooked fixture")
    emit(string.format("row_verified skill=%d cost=%d magnification=%d hits=%d sequence=%d",row.ID,row.Cost,row.magnification,row.hitCount,row.playSequencerId))
    local pre,post=RegisterHook("/Script/mucha.CPP_VM_BtlUnitParam:HandleBtlUnitParamUpdate",function(context)
        if updates>=100 or phase==3 then return end
        local ok,reason=pcall(function()
            local vm=context:get()
            if vm and vm:IsValid() then
                updates=updates+1
                observe(vm.BtlUnitParam,"update")
            end
        end)
        if not ok then emit("read_failed="..tostring(reason)) end
    end)
    assert(type(pre)=="number" and type(post)=="number","parameter observer registration failed")
end

function M.tick(units)
    if #units~=2 or phase==3 then return end
    local battle=StaticFindObject("/Script/mucha.Default__CPP_BFL_Battle")
    local parameter=battle:GetBattleUnitParameterByUnitId(1001,true)
    if not parameter or not parameter:IsValid() then return end
    observe(parameter,"sample")
    if phase==3 then return end
    if not granted then
        granted=true
        battle:SetUsableActiveSkill(1001,{401010,skill_id})
        battle:RefreshCommandSkill(1001)
        emit("transient_skill_list_requested unit=1001")
    end
    local managers=FindAllOf("CPP_UI_BtlCmdManager") or {}
    local view_models=FindAllOf("CPP_VM_BtlCmd") or {}
    if #managers~=1 or #view_models~=1 then return end
    local unique=managers[1]:GetCurrentActionUnitUniqueId()
    if unique<0 or battle:GetUnitIdByUniqueId(unique)~=1001 then return end
    local vm=view_models[1]
    if phase==0 then
        local key={Category=1,ID=401010}
        if not vm:CanActivateAction(key) then return end
        local target=battle:GetDefaultSkillTargetUnitUniqueId(unique,key.ID)
        assert(target>=0 and battle:GetUnitIdByUniqueId(target)==5,"baseline attack target mismatch")
        phase=1
        emit(string.format("baseline_attack_requested owner=%d target=%d",unique,target))
        vm:DecideActionKey(key)
        vm:DecideTarget({target},false)
        emit("baseline_attack_returned")
    elseif phase==1 and parameter:GetActionCountInBattle()>=2 then
        local key={Category=1,ID=skill_id}
        local allowed=vm:CanActivateAction(key)
        emit("converted_available="..tostring(allowed))
        if not allowed then return end
        before_hp,before_mp=parameter:GetHitPoint(),parameter:GetMagicPoint()
        assert(before_hp>0 and before_hp<parameter:GetMaxHitPoint() and before_mp>=4,"Cure needs a living injured caster with sufficient MP")
        phase=2
        emit(string.format("converted_command_requested owner=%d skill=%d target=%d hp=%d mp=%d",unique,skill_id,unique,before_hp,before_mp))
        vm:DecideActionKey(key)
        vm:DecideTarget({unique},false)
        emit("converted_command_returned")
    end
end

return M
