-- Controlled native battle; all changes live in the fresh fixture process.
local config=require('config')
assert(config.protectedSaves==true,'runner save locks required')
local log=assert(io.open(config.output..'/events.jsonl','w'))
local function quote(v)
    return '"'..tostring(v):gsub('\\','\\\\'):gsub('"','\\"'):gsub('[%z\1-\31]',function(c) return string.format('\\u%04x',string.byte(c)) end)..'"'
end
local function json(v)
    if type(v)=='number' then return v==v and tostring(v) or 'null' end
    if type(v)=='boolean' then return tostring(v) end
    if type(v)~='table' then return quote(v) end
    local a={};for k,x in pairs(v) do a[#a+1]=quote(k)..':'..json(x) end
    return '{'..table.concat(a,',')..'}'
end
local function emit(kind,data)
    data=data or {};data.kind=kind;log:write(json(data)..'\n');log:flush()
    if kind~='sample' then print('[RainFinaProbe] '..kind..'\n') end
end
local function xyz(v) return {x=v.X,y=v.Y,z=v.Z} end
local function val(v) local ok,r=pcall(function() return v:get() end);return ok and r or v end
local stage=require('stage')
local gameplay,system,world,travel,prepared,granted,requested,started,stopped
local last_setup,last_sample=-10,-10
local defended,captured={},{}
local captures={0,12,30,48,66,84,102,120,210,240}
local restored=false
local function setup()
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    if not prepared then
        local inventory=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataInventory')
        local data=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataUnit')
        local units={};data:GetSaveDataUnitParameterList(units)
        assert(#units==8,'fresh fixture required; no gameplay save may be loaded')
        assert(data:GetEquipmentId(1008,4,0)==-1 and inventory:FindInventory(config.vision)==0,'unexpected fixture inventory')
        inventory:AddInventory(config.vision,1);data:SetEquipmentId(1008,config.vision,0)
        prepared=true
    end
    stage.tick()
    local p=battle:GetBattleUnitParameterByUnitId(1008,true)
    if not p or not p:IsValid() then return end
    local ready=false
    for _,actor in ipairs(FindAllOf('CPP_BtlUnit') or {}) do
        local ep=actor.m_pUnitParameter
        if ep and ep:IsValid() and ep:GetUnitId()==config.enemy then
            if ep:GetMaxHitPoint()<=0 then return end
            ready=true
        end
    end
    if not ready then return end
    if not granted then
        local skill=StaticFindObject('/Script/mucha.Default__CPP_BFL_Skill'):GetSkillDataById(config.skill)
        assert(skill.ID==config.skill,'requested command missing')
        assert(p:GetEquipmentId(4,0)==config.vision,'wrong vision')
        local active={};p:GetActiveSkillListWithVision(active)
        local list={};local found=false
        for _,id in ipairs(active) do id=val(id);list[#list+1]=id;if id==config.skill then found=true end end
        emit('native_command_list',{skills=list,requestedFound=found,vision=config.vision})
        if not found and config.skill>=485000 then error('imported ability is absent from the native command list') end
        if not found then active[#active+1]=config.skill;battle:SetUsableActiveSkill(1008,active) end
        battle:SetBattleUnitLimitBurstPoint(1008,100);battle:RefreshCommandSkill(1008)
        granted=true;emit('loaded_skill',{id=skill.ID,sequence=skill.playSequencerId,hits=skill.hitCount,targetType=skill.TargetType})
        local resource_ok,mp=pcall(function() return p:GetMagicPoint() end)
        emit('owner_mp_before',{available=resource_ok,mp=tostring(mp),cost=skill.Cost})
    end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {};local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local unique=managers[1]:GetCurrentActionUnitUniqueId();if unique<0 then return end
    local owner=battle:GetUnitIdByUniqueId(unique);local vm=models[1]
    if owner~=1008 then
        if not (owner==1001 or owner==1002 or owner==1007) or defended[unique] then return end
        local key={Category=1,ID=400010};if not vm:CanActivateAction(key) then return end
        defended[unique]=true;vm:DecideActionKey(key);vm:DecideTarget({unique},false);return
    end
    if requested then return end
    local key={Category=1,ID=config.skill}
    if not vm:CanActivateAction(key) then emit('command_unavailable',{skill=config.skill});return end
    local target=battle:GetDefaultSkillTargetUnitUniqueId(unique,config.skill)
    assert(target>=0,'no native target')
    requested=gameplay:GetTimeSeconds(world)
    emit('command_requested',{time=requested,skill=config.skill,target=target})
    local targets={target}
    if config.allEnemies then
        -- The controlled stage allocates its two enemies consecutively after
        -- the four party members. Validate both identities before selecting.
        assert(battle:GetUnitIdByUniqueId(target)==config.enemy,'first fixture target differs')
        assert(battle:GetUnitIdByUniqueId(target+1)==config.secondEnemy,'second fixture target differs')
        targets={target,target+1}
    end
    emit('selected_targets',{targets=targets})
    vm:DecideActionKey(key);vm:DecideTarget(targets,false)
end
local handle
handle=LoopInGameThreadWithDelay(16,function()
    if stopped then return end
    local ok,err=pcall(function()
        gameplay=gameplay or StaticFindObject('/Script/Engine.Default__GameplayStatics')
        system=system or StaticFindObject('/Script/Engine.Default__KismetSystemLibrary')
        if not world then
            for _,w in ipairs(FindAllOf('World') or {}) do
                if w:IsValid() and w:GetFullName():find('/Game/Debug/BattleTest/DBG_BattleTest.',1,true) then world=w;break end
                if not travel and w:IsValid() and w:GetFullName():find('/Game/Map/Boot/MUCHA_Notify',1,true) then
                    travel=true
                    StaticFindObject('/Script/mucha.Default__CPP_DBG_BFL_BattleTest'):OpenBattleTestLevel(w,
                        system:Conv_SoftObjPathToSoftObjRef(system:MakeSoftObjectPath('/Game/Debug/BattleTest/DBG_BattleTest.DBG_BattleTest')))
                end
            end
        end
        if not world or not world:IsValid() then return end
        local t=gameplay:GetTimeSeconds(world)
        if not started and t-last_setup>=.25 then last_setup=t;setup() end
        if not requested then return end
        local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
        local caster=battle:GetBattleUnitByUnitIdWithVision(config.vision,false)
        for _,camera in ipairs(FindAllOf('CPP_BtlCamera') or {}) do
            if camera:IsValid() and camera:GetFullName():find('/Game/Debug/BattleTest/DBG_BattleTest.',1,true) and not camera:GetFullName():find('Default__',1,true) then
                local lens=camera:GetCurrentFocalLength();local base=camera:GetDefaultCurrentFocalLength()
                if not started and lens>base+.05 then started=t;emit('cast_camera_started',{time=t,defaultLens=base}) end
                if started and t-last_sample>=.016 then
                    last_sample=t
                    local rotation=camera:K2_GetActorRotation()
                    local sample={time=t,castElapsed=t-started,lens=lens,defaultLens=base,
                                  actor=camera:GetFullName(),
                                  camera=xyz(camera:K2_GetActorLocation()),rotation={pitch=rotation.Pitch,yaw=rotation.Yaw,roll=rotation.Roll}}
                    local component=camera:GetCineCameraComponent()
                    sample.componentLens=component.CurrentFocalLength
                    sample.componentLocation=xyz(component:K2_GetComponentLocation())
                    local cr=component:K2_GetComponentRotation()
                    sample.componentRotation={pitch=cr.Pitch,yaw=cr.Yaw,roll=cr.Roll}
                    local manager=gameplay:GetPlayerCameraManager(world,0)
                    sample.effectiveFov=manager:GetFOVAngle()
                    sample.effectiveLocation=xyz(manager:GetCameraLocation())
                    local mr=manager:GetCameraRotation()
                    sample.effectiveRotation={pitch=mr.Pitch,yaw=mr.Yaw,roll=mr.Roll}
                    sample.enemies={}
                    for _,actor in ipairs(FindAllOf('CPP_BtlUnit') or {}) do
                        local ep=actor.m_pUnitParameter
                        if ep and ep:IsValid() and (ep:GetUnitId()==config.enemy or ep:GetUnitId()==config.secondEnemy) then
                            sample.enemies[tostring(ep:GetUnitId())]={feet=xyz(actor:K2_GetActorLocation()),
                                head=xyz(actor.m_pSsPlayerComponent:GetSocketLocation(FName('NULL_Head'))),
                                radius=actor.m_pRootCapsuleComponent:GetScaledCapsuleRadius(),
                                capsuleHalfHeight=actor.m_pRootCapsuleComponent:GetScaledCapsuleHalfHeight()}
                        end
                    end
                    if caster and caster:IsValid() then
                        sample.caster=xyz(caster:K2_GetActorLocation())
                        sample.visible=not caster.bHidden
                        sample.head=xyz(caster.m_pSsPlayerComponent:GetSocketLocation(FName('NULL_Head')))
                        local anim_ok,anim=pcall(function() return caster.m_AnimationName:ToString() end)
                        if anim_ok then sample.casterAnimation=anim end
                    end
                    emit('sample',sample)
                    if sample.castElapsed>4 and math.abs(sample.effectiveFov-40.1586)<.02
                        and math.abs(sample.effectiveRotation.yaw)<.02
                        and math.abs(sample.effectiveRotation.pitch+10.5)<.02 then restored=true end
                end
            end
        end
        if started then
            for _,frame in ipairs(captures) do
                if not captured[frame] and t-started>=frame/60 then
                    captured[frame]=true
                    local file=config.output..'/frame-'..string.format('%04d',frame)..'.png'
                    system:ExecuteConsoleCommand(world,'HighResShot 1280x720 filename="'..file..'"',gameplay:GetPlayerController(world,0))
                    emit('capture_requested',{time=t,castElapsed=t-started,filename=file});break
                end
            end
            if restored and captured[240] then
                local resource_ok,mp=pcall(function() return battle:GetBattleUnitParameterByUnitId(1008,true):GetMagicPoint() end)
                emit('owner_mp_after',{available=resource_ok,mp=tostring(mp)})
                stopped=true;emit('complete');log:close();print('[RainFinaProbe] COMPLETE\n');CancelDelayedAction(handle)
            elseif t-started>15 then error('camera did not restore after the action')
            end
        elseif t-requested>15 then error('cast camera did not start after native command selection') end
    end)
    if not ok then stopped=true;emit('failure',{error=tostring(err)});log:close();print('[RainFinaProbe] FAILED '..tostring(err)..'\n');CancelDelayedAction(handle) end
end)
