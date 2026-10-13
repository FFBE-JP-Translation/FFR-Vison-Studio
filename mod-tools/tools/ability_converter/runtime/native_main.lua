-- Development entry for FFRAvailabilityRuntime. Staged disabled, observer mode.
-- A verified lifecycle/loadout binder must supply an enforcement callback and
-- command IDs before this can become a playable availability runtime.
local Probe = require("availability_probe")
local serial=0
local function emit(event, fields)
    fields.event=event
    print("[FFRAvailabilityNative] "..Probe.json(fields).."\n")
end

function FFRAvailabilityOnNativeGuard(job,actor,root,skill,index,actions,targets,native)
    serial=serial+1
    emit("native_guard",{sequence=serial,job=job,actor=actor,rootJob=root,skillId=skill,
        objectIndex=index,actionCount=actions,targetCount=targets,nativeAllowed=native})
    if serial==20000 then emit("native_observation_capacity",{limit=20000}) end
    return native
end

function FFRAvailabilityNativeInit()
    -- The native API records this thread as the only callback thread. Lua mod
    -- startup itself is not assumed to be the native game's execution thread.
    ExecuteInGameThread(function()
        local ok,reason=FFRAvailabilityNativeAttach(false,"")
        emit(ok and "native_attached" or "native_attach_failed",{mode="observe",reason=reason})
    end)
end

-- Reflected observations share the log to correlate battle/turn/owner events
-- with direct native jobs. These observations do not update availability state.
require("availability_probe_main")

-- UE4SS registers the C++ API before executing this script. The Lua side owns
-- the handshake, after both the callback and reflected observers are ready.
FFRAvailabilityNativeInit()
