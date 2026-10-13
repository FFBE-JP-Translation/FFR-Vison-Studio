#include "bridge_core.hpp"
#include <lua.hpp>
#include <array>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <filesystem>

int run_query_tests();

namespace {
int checks{};
void check(bool value,const char* label) { ++checks; if(!value) throw std::runtime_error(label); }
template<class T> void put(std::array<std::byte,0x3b0>& job,std::size_t offset,T value) { std::memcpy(job.data()+offset,&value,sizeof(T)); }
__declspec(noinline) bool fixture_guard(void* raw) {
    volatile auto* bytes=static_cast<volatile unsigned char*>(raw);
    return bytes[0x340]!=0;
}
ffr::Guard volatile invoke=&fixture_guard;
void run(lua_State* lua,const char* text) {
    if(luaL_dostring(lua,text)!=LUA_OK) throw std::runtime_error(lua_tostring(lua,-1));
}
}
int main() {
    try {
        check(ffr::file_sha256((std::filesystem::path(FFR_ROOT)/"tools/UE4SS/ue4ss/UE4SS.dll").wstring())=="7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d","native SHA256 matches pinned UE4SS");
        bool missingRejected=false;
        try { ffr::file_sha256(L"Z:/__ffr_missing_module_785184__"); } catch(const std::exception&) { missingRejected=true; }
        check(missingRejected,"missing module fails native fingerprint check");
        std::array<std::byte,0x3b0> job{};
        put(job,0x338,std::int32_t{880001}); put(job,0x340,std::uint8_t{1});
        put(job,0xc,std::int32_t{456}); put(job,0x100,std::uintptr_t{0x1234});
        put(job,0xf8,std::uintptr_t{0x5678}); put(job,0x30,std::int32_t{1}); put(job,0x40,std::int32_t{2});
        ffr::GuardContext snapshot;
        check(ffr::GuardBridge::snapshot(job.data(),snapshot),"snapshot read");
        check(snapshot.skillId==880001 && snapshot.actor==0x1234 && snapshot.rootJob==0x5678 && snapshot.objectIndex==456 && snapshot.actionCount==1 && snapshot.targetCount==2,"native offsets");
        check(!ffr::GuardBridge::snapshot(nullptr,snapshot),"invalid snapshot rejected");
        std::uintptr_t fallback=0x4321; put(job,0x100,std::uintptr_t{0}); put(job,0x28,reinterpret_cast<std::uintptr_t>(&fallback));
        check(ffr::GuardBridge::snapshot(job.data(),snapshot) && snapshot.actor==fallback,"early native rejection actor fallback");

        ffr::GuardBridge bridge; std::string error; int calls=0;
        check(!bridge.attach(&fixture_guard,{},true,[](const auto&){return true;},GetCurrentThreadId(),error),"empty enforcement rejected");
        check(!bridge.attach(&fixture_guard,{880001,880001},true,[](const auto&){return true;},GetCurrentThreadId(),error),"duplicate IDs rejected");
        check(bridge.attach(&fixture_guard,{880001},true,[&](const auto& c){++calls; return c.skillId==880001;},GetCurrentThreadId(),error),"detour installed");
        check(invoke(job.data()),"managed native success");
        put(job,0x340,std::uint8_t{0}); check(!invoke(job.data()),"native false cannot be overridden");
        check(calls==2,"native false reaches callback for cancellation");
        put(job,0x338,std::int32_t{880002}); put(job,0x340,std::uint8_t{1});
        check(invoke(job.data()) && calls==2,"unmanaged native success untouched");
        put(job,0x338,std::int32_t{880001});
        bool other=true; std::thread worker([&]{other=invoke(job.data());}); worker.join();
        check(!other && calls==2,"wrong-thread managed execution denied without Lua");
        bridge.invalidate_callback(); check(!invoke(job.data()),"stopped callback denies managed cast");
        check(bridge.detach(error),"quiescent test detour removed"); check(invoke(job.data()),"original code restored");

        check(bridge.attach(&fixture_guard,{},false,[](const auto&)->bool{throw std::runtime_error("observer error");},GetCurrentThreadId(),error),"observer installed");
        check(invoke(job.data()),"observer failure preserves original success");
        put(job,0x340,std::uint8_t{0}); check(!invoke(job.data()),"observer preserves native false");
        check(bridge.detach(error),"observer detached"); put(job,0x340,std::uint8_t{1});
        check(bridge.attach(&fixture_guard,{880001},true,[](const auto&)->bool{throw std::runtime_error("authorization error");},GetCurrentThreadId(),error),"failing authorizer installed");
        check(!invoke(job.data()),"authorizer error denies managed cast"); check(bridge.detach(error),"failing authorizer detached");
        check(bridge.attach(&fixture_guard,{880001},true,[&](const auto&){return invoke(job.data());},GetCurrentThreadId(),error),"reentrant fixture installed");
        check(!invoke(job.data()),"reentrant authorization denied"); check(bridge.detach(error),"reentrant fixture detached");

        auto* lua=luaL_newstate(); check(lua!=nullptr,"Lua created"); luaL_openlibs(lua);
        const std::string file=std::string(FFR_ROOT)+"/tools/ability_converter/runtime/availability.lua";
        if(luaL_dofile(lua,file.c_str())!=LUA_OK) throw std::runtime_error(lua_tostring(lua,-1));
        lua_setglobal(lua,"availability");
        run(lua,R"lua(
            engine=availability.new({{key='ability',gates={{key='limit',kind='limited',owner='equipping_actor',maximumUses=2,singleCastWhenDualWielding=true,uniqueSelectionOnMulticast=false}}}})
            assert(engine:begin_battle('battle'))
            assert(engine:register_owner('battle','owner',{'ability'}))
            assert(engine:begin_turn('battle','owner',1))
            cast='cast-1'
            function authorize(native)
                return engine:authorize('battle','owner','ability',cast,'group',native)
            end
        )lua");
        auto callback=[&](const ffr::GuardContext& c) {
            lua_getglobal(lua,"authorize"); lua_pushboolean(lua,c.nativeAllowed);
            if(lua_pcall(lua,1,1,0)!=LUA_OK) throw std::runtime_error(lua_tostring(lua,-1));
            const bool answer=lua_isboolean(lua,-1) && lua_toboolean(lua,-1);
            lua_pop(lua,1); return answer;
        };
        check(bridge.attach(&fixture_guard,{880001},true,callback,GetCurrentThreadId(),error),"real Lua detour installed");
        put(job,0x340,std::uint8_t{0}); check(!invoke(job.data()),"Lua native rejection");
        put(job,0x340,std::uint8_t{1}); check(!invoke(job.data()),"cancelled native token cannot revive");
        run(lua,"cast='cast-2'"); check(invoke(job.data()),"direct Lua authorization");
        check(!invoke(job.data()),"duplicate native callback cannot spend twice");
        run(lua,"cast='cast-3'; assert(engine:reserve('battle','owner','ability',cast,'group',true))");
        check(invoke(job.data()),"reserved Lua authorization");
        run(lua,"cast='cast-4'"); check(!invoke(job.data()),"native cast denied after use exhaustion");
        check(lua_gettop(lua)==0,"Lua stack balanced");
        check(bridge.detach(error),"Lua detour detached");
        const std::string hostFile=std::string(FFR_ROOT)+"/tools/ability_converter/runtime/native_host.lua";
        if(luaL_dofile(lua,hostFile.c_str())!=LUA_OK) throw std::runtime_error(lua_tostring(lua,-1));
        lua_setglobal(lua,"native_host");
        run(lua,R"lua(
            assert(engine:end_battle('battle'))
            assert(engine:begin_battle('battle-2'))
            assert(engine:register_owner('battle-2','owner',{'ability'}))
            assert(engine:begin_turn('battle-2','owner',1))
            resolved=false; cast='bound-cast'
            bound,ids=native_host.bind(engine,{[880001]='ability'},function(c)
                assert(c.actor==0x4321 and c.rootJob==0x5678 and c.objectIndex==456)
                assert(c.actionCount==1 and c.targetCount==2 and c.command=='ability')
                if not resolved then return nil end
                return {battle='battle-2',owner='owner',cast=cast,group='bound-group'}
            end)
            assert(#ids==1 and ids[1]==880001)
            assert(not pcall(native_host.bind,engine,{[880001]='unknown'},function() end))
            assert(not pcall(native_host.bind,engine,{},function() end))
        )lua");
        const auto boundCallback=[&](const ffr::GuardContext& c) {
            lua_getglobal(lua,"bound");
            lua_pushinteger(lua,static_cast<lua_Integer>(c.job)); lua_pushinteger(lua,static_cast<lua_Integer>(c.actor));
            lua_pushinteger(lua,static_cast<lua_Integer>(c.rootJob)); lua_pushinteger(lua,c.skillId);
            lua_pushinteger(lua,c.objectIndex); lua_pushinteger(lua,c.actionCount); lua_pushinteger(lua,c.targetCount);
            lua_pushboolean(lua,c.nativeAllowed);
            if(lua_pcall(lua,8,1,0)!=LUA_OK) throw std::runtime_error(lua_tostring(lua,-1));
            const bool answer=lua_isboolean(lua,-1) && lua_toboolean(lua,-1); lua_pop(lua,1); return answer;
        };
        check(bridge.attach(&fixture_guard,{880001},true,boundCallback,GetCurrentThreadId(),error),"bound host detour installed");
        check(!invoke(job.data()),"missing lifecycle identity denies native execution");
        run(lua,"resolved=true"); check(invoke(job.data()),"explicit host identity authorizes native cast");
        check(!invoke(job.data()),"host cannot duplicate logical cast");
        run(lua,"cast='native-failure'"); put(job,0x340,std::uint8_t{0});
        check(!invoke(job.data()),"bound host preserves native failure");
        put(job,0x340,std::uint8_t{1}); check(!invoke(job.data()),"bound host retains cancelled native token");
        run(lua,"cast='second-bound-cast'"); check(invoke(job.data()),"cancelled bound attempt spent no use");
        check(lua_gettop(lua)==0,"bound Lua stack balanced");
        check(bridge.detach(error),"bound host detached"); lua_close(lua);

        check(bridge.attach(&fixture_guard,{},false,[&](const auto&){return false;},GetCurrentThreadId(),error),"bounded observer attached");
        for(int index=0;index<20001;++index) if(!invoke(job.data())) throw std::runtime_error("observer changed native result");
        check(bridge.observations()==20000,"observer callback capacity");
        check(bridge.detach(error),"bounded observer detached");
        const auto queryChecks=run_query_tests();
        std::cout<<"{\"status\":\"passed\",\"checks\":"<<checks+queryChecks<<",\"guardChecks\":"<<checks<<",\"queryChecks\":"<<queryChecks<<",\"nativeDetour\":\"MinHook\",\"lua\":\"5.4.7\",\"nativeBattle\":\"not_run\"}\n";
        return 0;
    } catch(const std::exception& error) {
        std::cerr<<"FAILED: "<<error.what()<<"\n"; return 1;
    }
}
