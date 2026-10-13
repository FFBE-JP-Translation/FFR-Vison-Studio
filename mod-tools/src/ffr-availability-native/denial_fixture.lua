-- Temporary live boundary test. Loaded only by observe.ps1 -DenyConverted.
-- The staged runtime stays disabled/observe. This copy denies only test Fire.
local Probe=require('availability_probe')
local attach=FFRAvailabilityNativeAttach
assert(type(attach)=='function','native attach API unavailable')
local attempted=false
function FFRAvailabilityNativeAttach(enforce,ids)
    assert(not attempted and enforce==false and ids=='','unexpected fixture attach request')
    attempted=true
    local observe=FFRAvailabilityOnNativeGuard
    assert(type(observe)=='function','observer callback unavailable')
    function FFRAvailabilityOnNativeGuard(job,actor,root,skill,index,actions,targets,native)
        observe(job,actor,root,skill,index,actions,targets,native)
        assert(skill==900010,'unexpected managed fixture skill')
        print('[FFRAvailabilityNative] '..Probe.json({event='fixture_native_denial',skillId=skill,
            actor=actor,job=job,nativeAllowed=native,decision=false,scope='temporary_fire_denial'})..'\n')
        return false
    end
    local ok,reason=attach(true,'900010')
    print('[FFRAvailabilityNative] '..Probe.json({event='fixture_enforcement_attached',
        allowed=ok,reason=reason,skillId=900010,mode='enforce'})..'\n')
    return ok,reason
end
