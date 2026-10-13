-- Bounded diagnostic companion for the temporary headless observer runner.
-- Optional test-map travel requires an isolated SQEX save namespace or the
-- runner's held read-only handles on every original .sav (no write/delete share).
-- No main-save import. An explicit runner flag permits one transient test battle.
local sample = 0
local requested_travel = false
local inspected_test = false
local selection_attached = false
local driver = require("battle_driver")
print("[FFRBattleProbe] loaded\n")
LoopAsync(3000, function()
    sample = sample + 1
    local current = sample
    ExecuteInGameThread(function()
        print(string.format("[FFRBattleProbe] sample=%d\n", current))
        local settings_ok, settings_error = pcall(function()
            local settings = StaticFindObject("/Script/SQEXSaveGameSystemModule.Default__SQEXSaveGameSystemSettings")
            assert(settings and settings:IsValid(), "SQEX save settings unavailable")
            print("[FFRBattleProbe] saveTitle="..settings.GameTitle:ToString().."\n")
            if FFRBattleProbeOpenTest and current >= 2 and not requested_travel then
                assert(FFRBattleProbeProtectedSaves or settings.GameTitle:ToString():match("^FFR_Ability_Observer_%d+_%d+_%d+$"), "save isolation was not applied; test travel refused")
                local worlds = FindAllOf("World") or {}
                for _, world in ipairs(worlds) do
                    if world:IsValid() and world:GetFullName():find("/Game/Map/Boot/MUCHA_Notify",1,true) then
                        local system = StaticFindObject("/Script/Engine.Default__KismetSystemLibrary")
                        local debug_battle = StaticFindObject("/Script/mucha.Default__CPP_DBG_BFL_BattleTest")
                        assert(system and system:IsValid() and debug_battle and debug_battle:IsValid(), "test-map libraries unavailable")
                        local path=system:MakeSoftObjectPath("/Game/Debug/BattleTest/DBG_BattleTest.DBG_BattleTest")
                        local reference=system:Conv_SoftObjPathToSoftObjRef(path)
                        requested_travel = true
                        debug_battle:OpenBattleTestLevel(world,reference)
                        print("[FFRBattleProbe] native_test_map_travel_requested\n")
                        break
                    end
                end
            end
        end)
        if not settings_ok then print("[FFRBattleProbe] settings_failed="..tostring(settings_error).."\n") end
        for _, class in ipairs({"World", "GameInstance", "PlayerController", "GameStateBase",
                                "CPP_DBG_BtlTestEntryData", "CPP_BtlJobSkill"}) do
            local ok, err = pcall(function()
                local objects = FindAllOf(class) or {}
                print(string.format("[FFRBattleProbe] class=%s count=%d\n", class, #objects))
                for index, object in ipairs(objects) do
                    if index > 8 then break end
                    if object:IsValid() then
                        print(string.format("[FFRBattleProbe] object=%s address=%d\n",
                            object:GetFullName(), object:GetAddress()))
                    end
                end
            end)
            if not ok then print("[FFRBattleProbe] read_failed="..tostring(err).."\n") end
        end
        if not inspected_test then
            local entries = FindAllOf("CPP_DBG_BtlTestEntryData") or {}
            if #entries > 0 then
                inspected_test = true
                local ok, err = pcall(function()
                    local entry = entries[1]
                    print(string.format("[FFRBattleProbe] entry group=%d stage=%d event=%d\n",entry.battleGroupId,entry.stageId,entry.EventId))
                    for _, field in ipairs({"frinelidesUnitDataList","enemiesUnitDataList"}) do
                        local list = entry[field]
                        print(string.format("[FFRBattleProbe] entry %s count=%d\n",field,list:GetArrayNum()))
                        list:ForEach(function(index, remote)
                            local unit = remote:get()
                            print(string.format("[FFRBattleProbe] unit list=%s index=%d id=%d level=%d layout=%d weapon=%d vision=%d\n",field,index,unit.UnitId,unit.Level,unit.layoutId,unit.WeaponId,unit.equipVisionId))
                        end)
                    end
                    for _, widget in ipairs(FindAllOf("UserWidget") or {}) do
                        if widget:IsValid() and widget:GetFullName():find("BtlTest",1,true) then
                            print("[FFRBattleProbe] widget="..widget:GetFullName().."\n")
                            widget:GetClass():ForEachFunction(function(fn)
                                print("[FFRBattleProbe] widget_function="..fn:GetFullName().."\n")
                                if fn:GetFullName():find(":OnBattleBeginButtonPress",1,true) or fn:GetFullName():find(":Setup Entry Data",1,true) then
                                    fn:ForEachProperty(function(property)
                                        print("[FFRBattleProbe] widget_parameter="..property:GetFullName().."\n")
                                    end)
                                end
                            end)
                        end
                    end
                end)
                if not ok then print("[FFRBattleProbe] test_inspection_failed="..tostring(err).."\n") end
            end
        end
        if FFRBattleProbeStartBattle then
            local ok,err = pcall(function()
                if FFRBattleProbeSelectionJobs and not selection_attached then
                    require('selection_driver').setup();selection_attached=true
                end
                driver.tick()
            end)
            if not ok then print("[FFRBattleProbe] combat_driver_failed="..tostring(err).."\n") end
        end
    end)
    return sample >= (FFRBattleProbeResetSource and 40 or (FFRBattleProbeStartBattle and 30 or 15))
end)
