-- Observes reflected handlers only. It never returns a UFunction override or
-- writes an Unreal property. Observations cannot certify native-call coverage.
local M = {}
local ARRAY = {}
local function object_name(object)
    if object and object:IsValid() then return object:GetFullName() end
    return "invalid"
end
local function value(remote)
    return remote:get()
end
local function integers(array)
    assert(array:GetArrayNum() <= 64, "unexpectedly large action array")
    local result = setmetatable({}, ARRAY)
    array:ForEach(function(_, element) result[#result+1] = element:get() end)
    return result
end
local function delegate(remote)
    local v = value(remote)
    assert(v and v:IsValid(), "invalid delegate payload")
    return v
end

function M.install(host)
    assert(type(host.register) == "function" and type(host.emit) == "function", "missing probe host")
    local active, serial, registrations, failures, queries = true, 0, {}, {}, 0
    local function emit(event, fields)
        if not active then return end
        serial = serial+1
        if serial > 20000 then active=false; host.emit({event="trace_capacity",sequence=serial}); return end
        fields = fields or {}
        fields.event, fields.sequence = event, serial
        host.emit(fields)
    end
    local function hook(class, method, event, read)
        local path = "/Script/mucha."..class..":"..method
        local callback = function(context, ...)
            if not active or (failures[path] or 0) >= 3 then return end
            if event == "query_enable" or event == "query_activate" then
                queries = queries+1
                if queries > 2048 then
                    if queries == 2049 then emit("query_capacity", {path=path}) end
                    return
                end
            end
            local ok, fields = pcall(read, context, ...)
            if ok then
                fields.path = path
                emit(event, fields)
            else
                failures[path] = (failures[path] or 0)+1
                emit("read_failed", {path=path, error=tostring(fields), failures=failures[path]})
            end
            -- No return: returning false here would override native bools.
        end
        local ok, pre, post = pcall(host.register, path, callback)
        if ok and type(pre) == "number" and type(post) == "number" then
            registrations[#registrations+1] = {path=path, pre=pre, post=post}
            emit("registered", {path=path})
        else
            emit("registration_failed", {path=path, error=tostring(pre)})
        end
    end
    local function event_value(_, remote)
        local v = delegate(remote)
        return {payload=object_name(v)}
    end
    hook("CPP_UI_BattleSubsystem","HandleBeginBtl","battle_begin",function(_, remote)
        queries = 0
        return {payload=object_name(delegate(remote))}
    end)
    hook("CPP_UI_BattleSubsystem","HandleEndBtl","battle_end",event_value)
    hook("CPP_UI_BattleSubsystem","HandleBeginResult","result_begin",event_value)
    hook("CPP_UI_BattleSubsystem","HandleBeginGameOver","game_over",event_value)
    hook("CPP_UI_BattleSubsystem","HandleBeginTurn","turn_begin",function(_, remote)
        local v = delegate(remote)
        return {uniqueId=v.UniqueID, payload=object_name(v)}
    end)
    hook("CPP_BtlDelEventUnit","OnExecuteUpdateDeadState","dead_state",function(_, remote)
        local v = delegate(remote)
        return {uniqueId=v.UniqueID, payload=object_name(v)}
    end)
    local function command(_, remote)
        local v, list = delegate(remote), setmetatable({}, ARRAY)
        assert(v.cmdDecideDataList:GetArrayNum() <= 64, "unexpectedly large command batch")
        v.cmdDecideDataList:ForEach(function(_, element)
            local entry = element:get()
            list[#list+1] = {skillId=entry.actionId, uniqueId=entry.actionUnitUniqueId,
                            item=entry.isUseItem, targets=integers(entry.targetUnitUniqueIdList)}
        end)
        return {payload=object_name(v), commandId=v.CommandId, notConsume=v.isNotConsume, actions=list}
    end
    hook("CPP_BtlDelEventCmd","OnExecuteDecideCommand","command_decide",command)
    hook("CPP_BtlDelEventCmd","OnExecuteStackMimicRepeatCmd","repeat_stack",command)
    hook("CPP_BtlDelEventCmd","OnExcuteBeginEscape","escape_begin",event_value)
    local function skill(_, remote)
        local v = delegate(remote)
        local fields = {payload=object_name(v), skillId=v.SkillId, uniqueId=v.actionUnitUniqueId,
                        counterVisible=v.isVisibleCounter, nameVisible=v.isVisibleSkillName,
                        targets=integers(v.targetUnitUniqueIdList)}
        if host.owner then
            local ok, owner = pcall(host.owner, v.actionUnitUniqueId)
            if ok then fields.owner=owner else fields.ownerError=tostring(owner) end
        end
        return fields
    end
    hook("CPP_VM_BtlMsg","HandleBeginSkill","skill_begin_message",skill)
    hook("CPP_VM_BtlLibra","HandleSkillBegin","skill_begin_libra",skill)
    hook("CPP_BFL_Battle","IsEnableCommand","query_enable",function(_, unique, id)
        return {uniqueId=value(unique),skillId=value(id)}
    end)
    hook("CPP_BFL_Battle","CanUnitActivateSkill","query_activate",function(_, unique, id, item, hierarchy, all)
        return {uniqueId=value(unique),skillId=value(id),item=value(item),hierarchy=integers(value(hierarchy)),all=value(all)}
    end)
    emit("ready", {mode="observation_only", registered=#registrations})
    return {
        stop=function()
            active=false
            if host.unregister then
                for _,r in ipairs(registrations) do host.unregister(r.path,r.pre,r.post) end
            end
        end
    }
end

-- Small deterministic JSON encoder for the primitive trace records above.
-- The probe has no dependency on a particular UE4SS shared JSON package.
function M.json(value)
    local function quote(text)
        return '"'..text:gsub('[%z\1-\31\\"]',function(c)
            if c == '"' then return '\\"' end
            if c == '\\' then return '\\\\' end
            return string.format('\\u%04x', string.byte(c))
        end)..'"'
    end
    local kind = type(value)
    if kind == "string" then return quote(value) end
    if kind == "boolean" then return value and "true" or "false" end
    if kind == "number" then
        assert(value == value and value ~= math.huge and value ~= -math.huge, "non-finite trace number")
        return tostring(value)
    end
    if kind == "nil" then return "null" end
    assert(kind == "table", "unsupported trace value")
    local parts = {}
    if #value > 0 or getmetatable(value) == ARRAY then
        for _,entry in ipairs(value) do parts[#parts+1]=M.json(entry) end
        return '['..table.concat(parts,',')..']'
    end
    local keys = {}
    for k in pairs(value) do assert(type(k)=="string", "invalid trace key"); keys[#keys+1]=k end
    table.sort(keys)
    for _,k in ipairs(keys) do parts[#parts+1]=quote(k)..':'..M.json(value[k]) end
    return '{'..table.concat(parts,',')..'}'
end
return M
