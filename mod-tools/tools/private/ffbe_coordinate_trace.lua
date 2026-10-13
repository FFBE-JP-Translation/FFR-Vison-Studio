-- Passive observer for actual battles. No command, movement, camera, visibility,
-- save, level-travel, or game-speed setters. The runner supplies save protection.
local config = require('config')
assert(config.protectedSaves == true, 'original save read locks required')
assert(type(config.seconds) == 'number' and config.seconds > 0 and config.seconds <= 600)
local log = assert(io.open(config.output .. '/coordinates.jsonl', 'w'))
local function quote(value)
    return '"' .. tostring(value):gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('[%z\1-\31]',
        function(c) return string.format('\\u%04x', string.byte(c)) end) .. '"'
end
local function json(value)
    if type(value) == 'number' then return value == value and math.abs(value) < math.huge and tostring(value) or 'null' end
    if type(value) == 'boolean' then return tostring(value) end
    if type(value) ~= 'table' then return quote(value) end
    local values = {}
    for k, v in pairs(value) do values[#values + 1] = quote(k) .. ':' .. json(v) end
    return '{' .. table.concat(values, ',') .. '}'
end
local sample = 0
local function emit(kind, record)
    record = record or {}; record.kind = kind; record.sample = sample
    log:write(json(record) .. '\n'); log:flush()
end
local function valid(o) return o and o:IsValid() end
local function name(o) return valid(o) and o:GetFullName() or 'invalid' end
local function val(o) local ok, v = pcall(function() return o:get() end); return ok and v or o end
local function text(o) local ok, v = pcall(function() return o:ToString() end); return ok and v or tostring(o) end
local function xyz(o) return {x = o.X, y = o.Y, z = o.Z} end
local function rotation(o) return {pitch = o.Pitch, yaw = o.Yaw, roll = o.Roll} end
local function transform(o)
    return {translation = xyz(o.Translation), scale = xyz(o.Scale3D),
        quaternion = {x = o.Rotation.X, y = o.Rotation.Y, z = o.Rotation.Z, w = o.Rotation.W}}
end
local function attempt(record, key, fn)
    local ok, result = pcall(fn)
    if ok then record[key] = result else record[key .. 'Error'] = tostring(result) end
end
local function each(array, maximum, fn)
    local total = 0
    array:ForEach(function(index, remote)
        total = total + 1
        if total <= maximum then fn(val(remote), total - 1, index) end
    end)
    return total
end
local function objects(array, maximum)
    local result = {}; result.count = each(array, maximum, function(o, i) result[tostring(i)] = name(o) end)
    result.truncated = result.count > maximum
    return result
end
local function component_record(component)
    local record = {component = name(component)}
    if not valid(component) then return record end
    attempt(record, 'worldLocation', function() return xyz(component:K2_GetComponentLocation()) end)
    attempt(record, 'worldRotation', function() return rotation(component:K2_GetComponentRotation()) end)
    attempt(record, 'worldScale', function() return xyz(component:GetComponentScale()) end)
    attempt(record, 'relativeLocation', function() return xyz(component.RelativeLocation) end)
    attempt(record, 'relativeRotation', function() return rotation(component.RelativeRotation) end)
    attempt(record, 'relativeScale', function() return xyz(component.RelativeScale3D) end)
    attempt(record, 'parent', function() return name(component:GetAttachParent()) end)
    attempt(record, 'attachSocket', function() return text(component:GetAttachSocketName()) end)
    attempt(record, 'owner', function() return name(component:GetOwner()) end)
    attempt(record, 'visible', function() return component:IsVisible() end)
    attempt(record, 'hiddenInGame', function() return component.bHiddenInGame end)
    return record
end
local function actor_record(actor)
    local record = {actor = name(actor)}
    if not valid(actor) then return record end
    attempt(record, 'worldLocation', function() return xyz(actor:K2_GetActorLocation()) end)
    attempt(record, 'worldRotation', function() return rotation(actor:K2_GetActorRotation()) end)
    attempt(record, 'worldScale', function() return xyz(actor:GetActorScale3D()) end)
    attempt(record, 'hidden', function() return actor.bHidden end)
    return record
end
local function hierarchy(component)
    local chain, seen, depth = {}, {}, 0
    while valid(component) and depth < 32 do
        local key = name(component)
        if seen[key] then chain.cycle = key; break end
        seen[key] = true; chain[tostring(depth)] = component_record(component)
        component = component:GetAttachParent(); depth = depth + 1
    end
    chain.count = depth; chain.truncated = valid(component) and depth == 32 or false
    return chain
end
local function sprite(component)
    local record = component_record(component)
    if not valid(component) then return record end
    attempt(record, 'project', function() return name(component.SsProject) end)
    for _, key in ipairs({'PlayFrame', 'EndFrame', 'PlayRate', 'FlipH', 'FlipV', 'MulAlpha'}) do
        attempt(record, key, function() return component['Get' .. key](component) end)
    end
    attempt(record, 'playing', function() return component:IsPlaying() end)
    attempt(record, 'uuPerPixel', function() return component.UUPerPixel end)
    attempt(record, 'ancestors', function() return hierarchy(component) end)
    -- Return both true world and component-space transforms. A source leap can
    -- then be separated from actor movement and billboard/foot offsets.
    local socket_names = {root = true, Null_root = true, NULL_Center = true, NULL_Head = true, NULL_Foot = true}
    attempt(record, 'socketInventory', function()
        local names = component:GetAllSocketNames()
        local inventory = {}
        inventory.count = each(names, 256, function(socket, i)
            local label = text(socket)
            if i < 16 then inventory[tostring(i)] = label end
            if label:lower():find('null', 1, true) or label:lower():find('root', 1, true)
                or label:lower():find('foot', 1, true) then socket_names[label] = true end
        end)
        inventory.truncated = inventory.count > 256
        return inventory
    end)
    record.sockets = {}
    for label in pairs(socket_names) do
        local socket = {name = label}
        attempt(socket, 'exists', function() return component:DoesSocketExist(FName(label)) end)
        if socket.exists then
            attempt(socket, 'world', function() return transform(component:GetSocketTransform(FName(label), 0)) end)
            attempt(socket, 'component', function() return transform(component:GetSocketTransform(FName(label), 2)) end)
        end
        record.sockets[label] = socket
    end
    return record
end
local function unit_record(unit)
    local record = actor_record(unit)
    local parameter = unit.m_pUnitParameter
    if not valid(parameter) then return record end
    record.unitId = parameter:GetUnitId(); record.uniqueId = parameter:GetUniqueId()
    record.vision = name(parameter.m_pVision); record.visionOwner = name(parameter.m_pVisionOwner)
    record.sprite = sprite(unit.m_pSsPlayerComponent)
    record.components = {}
    for _, field in ipairs({'m_pRootCapsuleComponent', 'm_pFootComponent', 'm_pPenetrationAdjustComponent',
        'm_pBillboardComponent', 'm_pShakeComponent', 'm_pFootShadow', 'm_pCastShadow'}) do
        attempt(record.components, field, function() return component_record(unit[field]) end)
    end
    attempt(record, 'animationName', function() return text(unit.m_AnimationName) end)
    attempt(record, 'spriteScale', function() return unit.m_SsPlayerScale end)
    attempt(record, 'spriteOffset', function() return xyz(unit.m_SsPlayerOffset) end)
    attempt(record, 'spriteRotation', function() return rotation(unit.m_SsPlayerRotation) end)
    attempt(record, 'attackOffset', function() return xyz(unit.m_AttackOffestLocation) end)
    attempt(record, 'magicAura', function() return component_record(unit.m_pAuraEffect) end)
    attempt(record, 'nativeNiagara', function()
        local registry = {}
        registry.count = each(unit.m_SsNiagaraDatas, 64, function(data, index)
            local effect = data.NiagaraComponent
            local entry = component_record(effect); entry.nativeIndex = index
            if valid(effect) then
                attempt(entry, 'asset', function() return name(effect:GetAsset()) end)
                attempt(entry, 'ancestors', function() return hierarchy(effect) end)
            end
            registry[tostring(index)] = entry
        end)
        registry.truncated = registry.count > 64
        -- Only NiagaraComponent is reflected in FSsNiagaraData. The remaining
        -- private fields require a separate native read, never invented names.
        registry.unreflectedAttachmentFields = true
        return registry
    end)
    return record
end
local function snapshot()
    local gameplay = StaticFindObject('/Script/Engine.Default__GameplayStatics')
    local worlds = {}
    for _, unit in ipairs(FindAllOf('CPP_BtlUnit') or {}) do
        if valid(unit) and valid(unit.m_pUnitParameter) and not name(unit):find('Default__', 1, true) then
            local record = {}
            attempt(record, 'data', function() return unit_record(unit) end)
            attempt(record, 'worldSeconds', function() return gameplay:GetTimeSeconds(unit) end)
            emit('unit', record)
            local unit_name = name(unit)
            local world_key = unit_name:match('([^ ]+):PersistentLevel') or unit_name
            if not worlds[world_key] then worlds[world_key] = unit end
        end
    end
    for world_key, context in pairs(worlds) do
        local record = {world = world_key, isDebugFixture = world_key:find('/Game/Debug/BattleTest/', 1, true) ~= nil}
        attempt(record, 'seconds', function() return gameplay:GetTimeSeconds(context) end)
        attempt(record, 'viewport', function()
            local layout = StaticFindObject('/Script/UMG.Default__WidgetLayoutLibrary')
            local size = layout:GetViewportSize(context)
            return {width = size.X, height = size.Y, uiScale = layout:GetViewportScale(context)}
        end)
        attempt(record, 'camera', function()
            local manager = gameplay:GetPlayerCameraManager(context, 0)
            local camera = actor_record(manager)
            camera.location = xyz(manager:GetCameraLocation()); camera.rotation = rotation(manager:GetCameraRotation())
            camera.fov = manager:GetFOVAngle(); camera.viewTarget = name(manager:GetViewTarget())
            camera.defaultAspect = manager.DefaultAspectRatio
            return camera
        end)
        emit('world', record)
    end
    for _, manager in ipairs(FindAllOf('CPP_BtlManager') or {}) do
        if valid(manager) and not name(manager):find('Default__', 1, true) then
            local record = {manager = name(manager)}
            attempt(record, 'context', function()
                local units, jobs = manager.m_pUnitManager, manager.m_pBattleJobManager
                local state = {}
                if valid(units) then
                    state.units = objects(units.m_UnitList, 64)
                    state.commandUnit = name(units.m_pCmdSelectUnit)
                    state.targets = objects(units.m_TargetUnitList, 64)
                end
                if valid(jobs) then
                    state.jobs = {}
                    state.jobs.count = each(jobs.m_WorkingJobList, 16, function(job, index)
                        if not valid(job) then return end
                        local entry = {job = name(job), skill = name(job.m_pSkill),
                            actions = objects(job.m_ActionUnitList, 32), targets = objects(job.m_TargetUnitList, 32)}
                        attempt(entry, 'sequence', function() return name(job.m_pLevelSequenceActor) end)
                        attempt(entry, 'generatedSprites', function()
                            local generated = {}
                            generated.count = each(job.m_GeneratedSpriteStudioDatas, 64, function(data, i)
                                generated[tostring(i)] = {id = text(data.spriteStudioID), actor = actor_record(data.ssActor)}
                            end)
                            return generated
                        end)
                        state.jobs[tostring(index)] = entry
                    end)
                end
                return state
            end)
            emit('battle_context', record)
        end
    end
end
emit('observer_started', {mode = 'passive_normal_battle', noGameStateWrites = true,
    intervalMilliseconds = config.intervalMilliseconds or 100, maxSeconds = config.seconds})
local callback, elapsed = nil, 0
callback = LoopInGameThreadWithDelay(config.intervalMilliseconds or 100, function()
    elapsed = elapsed + (config.intervalMilliseconds or 100) / 1000; sample = sample + 1
    local ok, err = pcall(snapshot)
    if not ok then emit('observation_error', {error = tostring(err)}) end
    if elapsed >= config.seconds then
        emit('observer_complete', {samples = sample, scheduledSeconds = elapsed})
        log:close(); print('[FFBECoordinateTrace] COMPLETE\n'); CancelDelayedAction(callback)
    end
end)
