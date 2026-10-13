cmake_minimum_required(VERSION 3.22)
project(FFRBattleFixture LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
get_filename_component(FFR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
set(DEPS "${FFR_ROOT}/build/tooling")
set(SDK "${DEPS}/ue4ss-sdk-24b12662")
set(GENERATED "${FFR_ROOT}/build/abilities/native-bridge-sdk")
add_subdirectory(".." native-core EXCLUDE_FROM_ALL)
add_library(FFRBattleFixture SHARED mod.cpp)
add_dependencies(FFRBattleFixture ue4ss_import)
target_link_libraries(FFRBattleFixture PRIVATE bridge_core "${GENERATED}/UE4SS.lib")
target_include_directories(FFRBattleFixture SYSTEM PRIVATE "${GENERATED}/include" "${SDK}/UE4SS/include"
  "${SDK}/deps/first/LuaMadeSimple/include" "${SDK}/deps/first/LuaRaw/include"
  "${SDK}/deps/first/File/include" "${SDK}/deps/first/Input/include" "${SDK}/deps/first/String/include"
  "${DEPS}/fmt-11.2.0/include")
target_compile_definitions(FFRBattleFixture PRIVATE HAS_INPUT _DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR)
target_compile_options(FFRBattleFixture PRIVATE /W4 /EHsc /utf-8)
set_target_properties(FFRBattleFixture PROPERTIES OUTPUT_NAME main)
