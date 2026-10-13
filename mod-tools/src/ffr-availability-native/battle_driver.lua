-- Transient native battle fixture. Called only by the protected observer runner.
-- Main save slots are neither imported nor selected, and no progression is saved.
local M = {}
local attempted = false
local command_attempted = false
local observation_complete = false
local enemy_id = 5 -- Stock Goblin: moderate HP and ordinary early-game damage.
local function emit(text) print("[FFRBattleDriver] "..text.."\n") end
local converted = FFRBattleProbeConvertedAbility and require(FFRBattleProbeLifeSource and 'life_driver' or (FFRBattleProbeOwnedSource and 'owned_driver' or (FFRBattleProbeSourceAvailability and (FFRBattleProbeConvertedCase=="cooldown" and "cooldown_driver" or "source_driver") or (FFRBattleProbeLimitedConverted and "limited_driver" or (FFRBattleProbeDenyConverted and "deny_driver" or (FFRBattleProbeConvertedCase=="fire" and "fire_driver" or "converted_driver")))))) or nil
if FFRBattleProbeReturn then converted=require('return_driver') end
if FFRBattleProbeLoadoutSource then converted=require('loadout_driver') end
if FFRBattleProbeMultiCommand then converted=require('multicommand_driver') end
if FFRBattleProbeRepeatCommand then converted=require('repeat_driver') end

function M.tick()
    if attempted then
        local units=FindAllOf("CPP_BtlUnit") or {}
        emit("unit_count="..#units)
        for _,unit in ipairs(units) do
            local parameter=unit.m_pUnitParameter
            if parameter and parameter:IsValid() then
                emit(string.format("unit actor=%d id=%d hp=%d actions=%d",unit:GetAddress(),parameter:GetUnitId(),parameter:GetHitPoint(),parameter:GetActionCountInBattle()))
                if command_attempted and not observation_complete and parameter:GetUnitId()==1001
                    and parameter:GetHitPoint()>0 and parameter:GetActionCountInBattle()>=2 then
                    observation_complete=true
                    emit("stock_observation_complete")
                end
            end
        end
        local encounter_task=false
        for _,manager in ipairs(FindAllOf("CPP_TaskManager") or {}) do
            local task=manager.m_pTask
            if task and task:IsValid() then
                local state=task.m_pTaskState
                local states={}
                task.m_StateList:ForEach(function(_,value) states[#states+1]=tostring(value:get()) end)
                emit(string.format("task=%s address=%d state=%d states=%s",task:GetFullName(),task:GetAddress(),state and state:IsValid() and state:GetAddress() or 0,table.concat(states,",")))
                encounter_task=task:GetFullName():find("CPP_EncountTaskStartup ",1,true)~=nil
            end
        end
        if encounter_task and #units==0 then
            for _,widget in ipairs(FindAllOf("CPP_Encount_WBP_Base") or {}) do
                if widget:GetFullName():find("/Engine/Transient",1,true) then
                emit(string.format("encounter widget=%s playing=%s created=%s capture=%s invalid=%d",widget:GetFullName(),tostring(widget.m_IsPlayingEncount),tostring(widget.Created),tostring(widget.IsValidCapture),widget.m_InvalidCaptureCount))
                end
            end
        end
        local managers=FindAllOf("CPP_BtlManager") or {}
        emit("battle_manager_count="..#managers)
        for _,manager in ipairs(managers) do
            emit(string.format("battle_manager address=%d level_manager=%d",manager:GetAddress(),manager.m_pBattleLevelManager:GetAddress()))
            manager.m_BattleLevelList:ForEach(function(_,remote)
                local level=remote:get()
                if level and level:IsValid() then emit(string.format("level=%s loaded=%s visible=%s",level:GetFullName(),tostring(level:IsLevelLoaded()),tostring(level:IsLevelVisible()))) end
            end)
            for _,field in ipairs({"m_BattleLevelList","m_BattleLevelInstanceList"}) do
                manager.m_pBattleLevelManager[field]:ForEach(function(key,remote)
                    local bundle=remote:get()
                    local lighting=bundle.pLightingLevel
                    emit(string.format("bundle field=%s stage=%d levels=%d lighting=%s",field,key:get(),bundle.battleLevelList:GetArrayNum(),lighting and lighting:IsValid() and lighting:GetFullName() or "invalid"))
                    bundle.battleLevelList:ForEach(function(_,item)
                        local level=item:get()
                        emit(string.format("bundle_level=%s loaded=%s visible=%s",level:GetFullName(),tostring(level:IsLevelLoaded()),tostring(level:IsLevelVisible())))
                    end)
                end)
            end
        end
        for _,level in ipairs(FindAllOf("LevelStreamingDynamic") or {}) do
            if level:GetFullName():find("/Game/Debug/BattleTest/DBG_BattleTest.",1,true) then
                emit(string.format("stream=%s loaded=%s visible=%s",level:GetFullName(),tostring(level:IsLevelLoaded()),tostring(level:IsLevelVisible())))
            end
        end
        if converted then
            converted.tick(units)
        elseif #units==2 and not command_attempted then
            local battle=StaticFindObject("/Script/mucha.Default__CPP_BFL_Battle")
            local command_managers=FindAllOf("CPP_UI_BtlCmdManager") or {}
            local view_models=FindAllOf("CPP_VM_BtlCmd") or {}
            emit(string.format("command_candidates managers=%d view_models=%d",#command_managers,#view_models))
            if #command_managers==1 and #view_models==1 then
                local owner=command_managers[1]:GetCurrentActionUnitUniqueId()
                if owner>=0 and battle:GetUnitIdByUniqueId(owner)==1001 then
                    -- Stock DT_SkillData: Rain's ordinary attack is 401010.
                    -- Use the live command view model to perform selection;
                    -- it constructs the command payload and emits game events.
                    local key={Category=1,ID=401010}
                    local vm=view_models[1]
                    if vm:CanActivateAction(key) then
                        local target=battle:GetDefaultSkillTargetUnitUniqueId(owner,key.ID)
                        assert(target>=0 and battle:GetUnitIdByUniqueId(target)==enemy_id,"stock attack target mismatch")
                        command_attempted=true
                        emit(string.format("stock_command_requested owner=%d skill=%d target=%d",owner,key.ID,target))
                        vm:DecideActionKey(key)
                        vm:DecideTarget({target},false)
                        emit("stock_command_handler_returned")
                    end
                end
            end
        end
        return
    end
    assert(FFRBattleProbeProtectedSaves, "original saves must be locked by the runner")
    local entries = FindAllOf("CPP_DBG_BtlTestEntryData") or {}
    local layouts = FindAllOf("WBP_DBG_BtlTest_Layout_C") or {}
    if #entries ~= 1 or #layouts ~= 1 then return end
    local worlds = FindAllOf("World") or {}
    local test_world = false
    for _,world in ipairs(worlds) do
        if world:IsValid() and world:GetFullName():find("/Game/Debug/BattleTest/DBG_BattleTest.",1,true) then test_world=true end
    end
    if not test_world then return end
    attempted = true
    local assets = StaticFindObject("/Script/mucha.Default__CPP_BFL_Asset")
    local battle = StaticFindObject("/Script/mucha.Default__CPP_BFL_Battle")
    assert(assets and assets:IsValid() and battle and battle:IsValid(), "battle libraries unavailable")
    if converted then converted.setup() end
    local pre,post=RegisterHook("/Script/mucha.CPP_UI_BattleSubsystem:HandleBeginTurn",function(_,remote)
        local ok,reason=pcall(function()
            local unique=remote:get().UniqueID
            local parameter=battle:GetBattleUnitParameterWithVision(unique,false)
            assert(parameter and parameter:IsValid(),"turn parameter unavailable")
            local actor=parameter.m_pVisionOwner
            if not actor or not actor:IsValid() then actor=parameter.m_pOwnerBtlUnit end
            assert(actor and actor:IsValid(),"turn owner unavailable")
            local owner_parameter=actor.m_pUnitParameter
            assert(owner_parameter and owner_parameter:IsValid(),"equipping owner parameter unavailable")
            emit(string.format("turn_owner unique=%d actor=%d parameter=%d unit=%d turn=%d",unique,actor:GetAddress(),owner_parameter:GetAddress(),owner_parameter:GetUnitId(),owner_parameter:GetActionCountInBattle()))
            local active,with_vision={},{}
            owner_parameter:GetActiveSkillList(active)
            owner_parameter:GetActiveSkillListWithVision(with_vision)
            local function ids(list)
                local result={}
                for _,value in ipairs(list) do
                    local id=type(value)=='number' and value or value:get()
                    assert(type(id)=='number' and id==math.floor(id),'non-integer active skill')
                    result[#result+1]=id
                end
                assert(#result<=2048,'unexpected active skill list size')
                table.sort(result);return table.concat(result,',')
            end
            emit(string.format("turn_owner_loadout unique=%d actor=%d unit=%d active=%s with_vision=%s",
                unique,actor:GetAddress(),owner_parameter:GetUnitId(),ids(active),ids(with_vision)))
            emit(string.format('turn_owner_equipment unique=%d actor=%d unit=%d vision=%d',
                unique,actor:GetAddress(),owner_parameter:GetUnitId(),owner_parameter:GetEquipmentId(4,0)))
        end)
        if not ok then emit("turn_owner_failed="..tostring(reason)) end
        -- Observation only; no override is returned.
    end)
    assert(type(pre)=="number" and type(post)=="number","turn owner observer registration failed")
    local choices = {}
    local stages=assets:GetBattleStageIdAndRowName()
    local function add_stage(key,value)
        choices[#choices+1]={id=key,name=type(value)=="string" and value or value:ToString()}
    end
    if type(stages)=="table" then
        -- UE4SS's GetNonTrivialLocal map pusher returns a Lua table whose keys
        -- and values are GetParam wrappers, rather than ordinary Lua values.
        for key,value in pairs(stages) do add_stage(key:get(),value:get()) end
    else
        stages:ForEach(function(key,value) add_stage(key:get(),value:get()) end)
    end
    table.sort(choices,function(a,b) return a.id<b.id end)
    local selected
    for _,choice in ipairs(choices) do
        if choice.id >= 0 then
            local stage = battle:GetStageAsset(FName(choice.name))
            local levels=stage.battleLevelList
            local count = type(levels)=="table" and #levels or levels:GetArrayNum()
            emit(string.format("stage id=%d name=%s levels=%d",choice.id,choice.name,count))
            if count>0 and (not selected or choice.id==5) then selected=choice end
        end
    end
    assert(selected, "no loaded native battle stage has a level reference")
    local entry = entries[1]
    local friendly_ids=FFRBattleProbeOwnedSource and {1001,1002} or {1001}
    local friendly_layouts=FFRBattleProbeOwnedSource and {1010,1020} or {1010}
    assert(entry.frinelidesUnitDataList:GetArrayNum()==6 and entry.enemiesUnitDataList:GetArrayNum()==8, "unexpected debug roster shape")
    -- Stock DT_UnitParameter: Rain=1001, Goblin=5. Use explicit encounter
    -- roster IDs and the verified single-unit layout 10 / friendly layout 1010.
    entry.frinelidesUnitDataList:ForEach(function(index,remote)
        local unit=remote:get()
        unit.UnitId=friendly_ids[index] or -1
        if friendly_ids[index] then unit.Level=10;unit.layoutId=friendly_layouts[index] end
    end)
    entry.enemiesUnitDataList:ForEach(function(index,remote)
        local unit=remote:get()
        unit.UnitId=index==1 and enemy_id or -1
        if index==1 then unit.Level=1; unit.layoutId=10 end
    end)
    entry.stageId=selected.id
    entry.battleGroupId=1
    entry.EventId=-1
    entry.frinelidesUnitDataList:ForEach(function(index,remote)
        assert(remote:get().UnitId==(friendly_ids[index] or -1),"friendly roster write did not persist")
    end)
    entry.enemiesUnitDataList:ForEach(function(index,remote)
        assert(remote:get().UnitId==(index==1 and enemy_id or -1),"enemy roster write did not persist")
    end)
    -- Shipping SetBattleEntry replaces the requested stage with the level
    -- manager's current stage. Prepare that manager before the normal encounter
    -- entry. The shipping SetDebugBattleEntryData body is a no-op; the native
    -- actors use the current process's initial parameters, not these overrides.
    local debug_battle=StaticFindObject("/Script/mucha.Default__CPP_DBG_BFL_Battle")
    local parameters={}
    for _,field in ipairs({"frinelidesUnitDataList","enemiesUnitDataList"}) do
        entry[field]:ForEach(function(_,remote)
            local unit=remote:get()
            if unit.UnitId~=-1 then parameters[#parameters+1]=unit end
        end)
    end
    local maps=FindAllOf("CPP_MapManager") or {}
    assert(#maps==1,"expected one map manager for the transient test world")
    local managers=FindAllOf("CPP_BtlManager") or {}
    assert(#managers==1 and type(FFRBattleFixtureLoadStage)=="function","native stage fixture unavailable")
    local loaded,reason=FFRBattleFixtureLoadStage(managers[1].m_pBattleLevelManager:GetAddress(),selected.id)
    assert(loaded,reason)
    emit("native_stage_prepared="..selected.id)
    -- This UE4SS build's nested Lua-array marshaller uses stack index 1 even
    -- inside a struct. Native TArray userdata takes its separate deep-copy path.
    local holders={}
    local function integers(values)
        local holder=StaticConstructObject(StaticFindObject("/Script/mucha.CPP_BtlUnitSelectDecideDelVal"),maps[1])
        assert(holder and holder:IsValid(),"array holder construction failed")
        holder.targetUniqueIdList=values
        assert(holder.targetUniqueIdList:GetArrayNum()==#values,"native integer array mismatch")
        holders[#holders+1]=holder
        return holder.targetUniqueIdList
    end
    local roster=StaticConstructObject(StaticFindObject("/Script/mucha.CPP_DBG_BtlTestEntryData"),maps[1])
    assert(roster and roster:IsValid(),"native roster construction failed")
    roster.frinelidesUnitDataList=parameters
    assert(roster.frinelidesUnitDataList:GetArrayNum()==#friendly_ids+1,"native test parameters mismatch")
    debug_battle:SetDebugBattleEntryData({isUseTestUnitParam=true,unitParamterList=roster.frinelidesUnitDataList})
    local request={friendliesUnitIdList=integers(friendly_ids),friendliesLocationIdList=integers(friendly_layouts),
        enemiesUnitIdList=integers({enemy_id}),enemiesLocationIdList=integers({10}),
        CanEscape=true,probabilityOfSuccessfulEscape=100,isResultSkipOnWin=true,
        isResultSkipOnLose=true,battleGroupId=1,battleStageId=selected.id,battleEventId=-1,
        bgmCueName="",ap=0,regionId=-1,preemptiveRelation=0,isNotifyPreemtiveAttack=false,
        isStartupByBattleTest=true,isContinueBGM=false,isBounty=false}
    emit(string.format("start_requested stage=%d friendly=%s enemy=%d group=1",selected.id,table.concat(friendly_ids,','),enemy_id))
    if FFRBattleProbeReturn then
        local test=StaticFindObject('/Script/mucha.Default__CPP_DBG_BFL_BattleTest')
        converted.restart=function()
            -- Construct fresh native arrays for each request; old encounter
            -- payload UObjects may have been collected after the prior battle.
            request.friendliesUnitIdList=integers(friendly_ids)
            request.friendliesLocationIdList=integers(friendly_layouts)
            request.enemiesUnitIdList=integers({enemy_id})
            request.enemiesLocationIdList=integers({10})
            test:BegineBattleInBattleTest(maps[1],request)
            emit('native_test_entry_returned')
        end
        converted.restart()
    else
        maps[1]:Encount(request,true)
    end
    emit("start_handler_returned")
end

return M
