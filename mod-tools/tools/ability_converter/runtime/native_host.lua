-- Connect the native guard transport to the canonical availability engine.
-- Binding the native events and logical identities is a separate host task.
-- Never manufacture a logical cast token from a raw job/actor address here.
local M = {}
local function integer(value)
    return type(value)=="number" and value==math.floor(value) and value>=0 and value<=math.maxinteger
end

function M.bind(engine, commands, resolve)
    assert(type(engine)=="table" and type(engine.authorize)=="function", "availability engine required")
    assert(type(commands)=="table" and type(resolve)=="function", "explicit native command and context bindings required")
    local bindings, ids = {}, {}
    for id,key in pairs(commands) do
        assert(integer(id) and id>0 and id<=2147483647, "invalid native skill ID")
        assert(type(key)=="string" and engine.commands[key], "unregistered source command")
        assert(#ids<512, "native command capacity")
        bindings[id]=key; ids[#ids+1]=id
    end
    assert(#ids>0, "empty native command binding")
    table.sort(ids)
    local function guard(job, actor, root, skill, object_index, actions, targets, native)
        assert(type(native)=="boolean", "native result must be boolean")
        local command=bindings[skill]
        if not command then return native end
        if not integer(job) or job==0 or not integer(actor) or not integer(root)
            or not integer(object_index) or not integer(actions) or not integer(targets) then return false end
        local context=resolve({job=job, actor=actor, rootJob=root, skillId=skill,
            objectIndex=object_index, actionCount=actions, targetCount=targets,
            nativeAllowed=native, command=command})
        if type(context)~="table" then return false end
        -- The engine checks identity types, owner/loadout membership, turn
        -- readiness, prior reservations, native rejection and replayed tokens.
        return engine:authorize(context.battle,context.owner,command,context.cast,context.group,native)
    end
    return guard, ids
end
return M
