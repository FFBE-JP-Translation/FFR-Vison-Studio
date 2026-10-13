// Temporary test-fixture helper. This DLL is not part of the availability
// runtime or its staged package. It prepares one stock Plain battle stage.
#include "bridge_core.hpp"
#include <Mod/CppUserModBase.hpp>
#include <LuaMadeSimple/LuaMadeSimple.hpp>
#include <array>
#include <cstring>
#include <cstdio>
#include <MinHook.h>
#include <intrin.h>

namespace {
using RC::LuaMadeSimple::Lua;
bool requested{};
using BeginBattle=void(*)(void*);
BeginBattle original_begin{};
const Lua* begin_lua{};
DWORD begin_thread{};
std::wstring module_path(HMODULE module) {
    std::array<wchar_t,32768> path{};
    const auto n=GetModuleFileNameW(module,path.data(),static_cast<DWORD>(path.size()));
    if(!n || n>=path.size()) throw std::runtime_error("cannot resolve module path");
    return {path.data(),n};
}
template<class T> T read(std::uintptr_t address) {
    T value{}; SIZE_T count{};
    if(!ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<void*>(address),&value,sizeof(value),&count) || count!=sizeof(value))
        throw std::runtime_error("fixture address unreadable");
    return value;
}
void observed_begin(void* subsystem) {
    const auto caller=reinterpret_cast<std::uintptr_t>(_ReturnAddress());
    const auto address=reinterpret_cast<std::uintptr_t>(subsystem);
    unsigned char before{};
    bool readable=true;
    try { before=read<unsigned char>(address+0x80); }
    catch(...) { readable=false; }
    original_begin(subsystem);
    // This observer never changes the native lifecycle result or skips it.
    // A missing/stopped Lua resolver receives no callback and fails closed at
    // its separate managed-command gate. The detour stays pinned until exit.
    if(!readable || !begin_lua || GetCurrentThreadId()!=begin_thread) return;
    const auto stack=begin_lua->get_stack_size();
    try {
        if(!begin_lua->is_global_function("FFRAvailabilityOnNativeBattleBegin")) return;
        begin_lua->prepare_function_call("FFRAvailabilityOnNativeBattleBegin");
        begin_lua->set_integer(static_cast<std::int64_t>(address));
        begin_lua->set_bool(before!=0);
        begin_lua->set_bool(read<unsigned char>(address+0x80)!=0);
        begin_lua->set_integer(static_cast<std::int64_t>(caller-reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr))));
        begin_lua->call_function(4,0);
        while(begin_lua->get_stack_size()>stack) begin_lua->discard_value(-1);
    } catch(...) {
        while(begin_lua->get_stack_size()>stack) begin_lua->discard_value(-1);
        std::printf("[FFRBattleFixture] Native begin observer callback failed.\n");
    }
}
int observe_begin(const Lua& lua) {
    try {
        if(original_begin || lua.get_stack_size()!=0) throw std::runtime_error("native begin observer already attached or invalid arguments");
        if(!lua.is_global_function("FFRAvailabilityOnNativeBattleBegin")) throw std::runtime_error("native begin callback missing");
        lua.prepare_function_call("IsInGameThread");lua.call_function(0,1);
        if(!lua.get_bool(-1)) throw std::runtime_error("native begin observer requires the game thread");
        const auto target=reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr))+0x515c4c0;
        constexpr std::array<unsigned char,16> expected{0x40,0x53,0x48,0x83,0xec,0x20,0x48,0x8b,0xd9,0xc6,0x81,0x80,0,0,0,1};
        if(read<std::array<unsigned char,16>>(target)!=expected) throw std::runtime_error("native begin prologue changed");
        HMODULE pinned{};
        if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,
            reinterpret_cast<LPCWSTR>(&observe_begin),&pinned)) throw std::runtime_error("cannot pin native begin observer");
        auto result=MH_Initialize();
        if(result!=MH_OK && result!=MH_ERROR_ALREADY_INITIALIZED) throw std::runtime_error(MH_StatusToString(result));
        result=MH_CreateHook(reinterpret_cast<void*>(target),reinterpret_cast<void*>(&observed_begin),reinterpret_cast<void**>(&original_begin));
        if(result!=MH_OK) throw std::runtime_error(MH_StatusToString(result));
        begin_lua=&lua;begin_thread=GetCurrentThreadId();
        result=MH_EnableHook(reinterpret_cast<void*>(target));
        if(result!=MH_OK) {
            MH_RemoveHook(reinterpret_cast<void*>(target));original_begin=nullptr;begin_lua=nullptr;
            throw std::runtime_error(MH_StatusToString(result));
        }
        lua.set_bool(true);lua.set_string("native begin observer attached");return 2;
    } catch(const std::exception& error) { lua.set_bool(false);lua.set_string(error.what());return 2; }
}
int load_stage(const Lua& lua) {
    try {
        if(requested) throw std::runtime_error("fixture stage was already requested");
        if(lua.get_stack_size()!=2 || !lua.is_integer(1) || !lua.is_integer(2))
            throw std::runtime_error("expected battle-level manager address and stock stage ID");
        const auto manager=static_cast<std::uintptr_t>(lua.get_integer(1));
        const auto stage=static_cast<std::int32_t>(lua.get_integer(1));
        if(stage!=5) throw std::runtime_error("fixture supports stock Plain stage 5 only");
        lua.prepare_function_call("IsInGameThread"); lua.call_function(0,1);
        if(!lua.get_bool(-1)) throw std::runtime_error("fixture must run on the game thread");
        const auto base=reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
        if(read<std::uintptr_t>(manager)!=base+0x85cc0b0 || read<std::int32_t>(manager+0xc8)!=-1)
            throw std::runtime_error("unexpected class or already initialized battle stage");
        const auto target=base+0x4f61570;
        constexpr std::array<unsigned char,15> expected{0x40,0x55,0x53,0x56,0x57,0x41,0x54,0x48,0x8d,0xac,0x24,0x30,0xff,0xff,0xff};
        if(read<std::array<unsigned char,15>>(target)!=expected) throw std::runtime_error("stage-loader prologue changed");
        const auto load_registered=base+0x4f59880;
        constexpr std::array<unsigned char,14> load_expected{0x48,0x89,0x5c,0x24,0x18,0x48,0x89,0x7c,0x24,0x20,0x55,0x48,0x8b,0xec};
        if(read<std::array<unsigned char,14>>(load_registered)!=load_expected) throw std::runtime_error("registered-stage loader prologue changed");
        requested=true;
        // Native caller 0x144f61b90 invokes this with manager, stage ID and
        // force-instance flag, then stores the chosen stage at manager+0xc8.
        // Force-instance supports the standalone debug world's streamed levels.
        reinterpret_cast<void(*)(void*,std::int32_t,bool)>(target)(reinterpret_cast<void*>(manager),stage,true);
        std::memcpy(reinterpret_cast<void*>(manager+0xc8),&stage,sizeof(stage));
        // Registration leaves the bundle's streaming-level pointers empty.
        // This native no-argument method owns its temporary stage-ID array and
        // requests the assets and callbacks that construct the streamed levels.
        reinterpret_cast<void(*)(void*)>(load_registered)(reinterpret_cast<void*>(manager));
        lua.set_bool(true); lua.set_string("native stock stage requested"); return 2;
    } catch(const std::exception& error) {
        lua.set_bool(false); lua.set_string(error.what()); return 2;
    }
}
// Read-only access to the shipping lighting collector's unreflected current key.
// Used only when supplying the disposable debug world's absent field assets.
int lighting_key(const Lua& lua) {
    try {
        if(lua.get_stack_size()!=1 || !lua.is_integer(1)) throw std::runtime_error("expected lighting collector address");
        const auto address=static_cast<std::uintptr_t>(lua.get_integer(1));
        const auto key=read<std::int32_t>(address+0x90);
        if(key < -1 || key>100000) throw std::runtime_error("unexpected lighting key");
        lua.set_integer(key);return 1;
    } catch(const std::exception& error) { lua.set_nil();lua.set_string(error.what());return 2; }
}
int equipment_context(const Lua& lua) {
    try {
        if(lua.get_stack_size()!=2 || !lua.is_integer(1) || !lua.is_integer(2))
            throw std::runtime_error("expected map and active battle UI subsystem addresses");
        const auto manager=static_cast<std::uintptr_t>(lua.get_integer(1));
        const auto ui=static_cast<std::uintptr_t>(lua.get_integer(1));
        lua.prepare_function_call("IsInGameThread");lua.call_function(0,1);
        if(!lua.get_bool(-1)) throw std::runtime_error("equipment fixture requires game thread");
        const auto base=reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
        // The native equipment API calls IsDuringEncount (0x14505b340),
        // which obtains this exact map manager and reads its +0x2fc flag.
        const auto actual=reinterpret_cast<void*(*)()>(base+0x5055250)();
        if(manager!=reinterpret_cast<std::uintptr_t>(actual) || read<unsigned char>(manager+0x2fc)!=0 || read<unsigned char>(ui+0x80)!=1)
            throw std::runtime_error("unexpected debug map/battle context");
        // Normal encounter startup writes this flag at 0x14504b73d. Debug
        // startup bypasses it. Supply that missing fixture context only;
        // equipment mutation itself stays in FFR's complete native API.
        const unsigned char active=1;
        std::memcpy(reinterpret_cast<void*>(manager+0x2fc),&active,1);
        lua.set_bool(true);lua.set_string("debug equipment context prepared");return 2;
    } catch(const std::exception& error) { lua.set_bool(false);lua.set_string(error.what());return 2; }
}
class FixtureMod final : public RC::CppUserModBase {
public:
    FixtureMod() { ModName=STR("FFRBattleFixture"); ModVersion=STR("0.1.0"); ModDescription=STR("Temporary protected stock battle fixture"); }
    void on_lua_start(RC::StringViewType name,Lua&,Lua& main,Lua&,Lua*) override {
        if(name==STR("FFRBattleProbe")) {
            main.register_function("FFRBattleFixtureLoadStage",load_stage);
            main.register_function("FFRBattleFixtureLightingKey",lighting_key);
            main.register_function("FFRBattleFixtureEquipmentContext",equipment_context);
        }
        if(name==STR("FFRAvailabilityRuntime")) {
            main.register_function("FFRBattleFixtureObserveBegin",observe_begin);
        }
    }
    void on_lua_stop(RC::StringViewType name,Lua&,Lua&,Lua&,Lua*) override {
        if(name==STR("FFRAvailabilityRuntime")) { begin_lua=nullptr; }
    }
    ~FixtureMod() override { begin_lua=nullptr; }
};
static_assert(sizeof(RC::CppUserModBase)==0xc0);
}
extern "C" __declspec(dllexport) RC::CppUserModBase* start_mod() {
    try {
        const auto ue4ss=GetModuleHandleW(L"UE4SS.dll");
        if(!ue4ss || ffr::file_sha256(module_path(ue4ss))!="7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d" ||
           ffr::file_sha256(module_path(GetModuleHandleW(nullptr)))!="e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad")
            throw std::runtime_error("unsupported fixture binary fingerprint");
        return new FixtureMod();
    } catch(const std::exception& error) { std::printf("[FFRBattleFixture] %s\n",error.what()); return nullptr; }
}
extern "C" __declspec(dllexport) void uninstall_mod(RC::CppUserModBase* mod) { delete mod; }
