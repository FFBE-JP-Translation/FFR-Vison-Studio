cmake_minimum_required(VERSION 3.22)
project(FFRSelectionProbe LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 23)
set(CMAKE_MSVC_RUNTIME_LIBRARY MultiThreadedDLL)
get_filename_component(FFR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)
set(DEPS "${FFR_ROOT}/build/tooling")
set(SDK "${DEPS}/ue4ss-sdk-24b12662")
set(GENERATED "${FFR_ROOT}/build/abilities/native-bridge-sdk")
add_subdirectory(".." native-core EXCLUDE_FROM_ALL)
add_library(FFRSelectionProbe SHARED mod.cpp)
add_dependencies(FFRSelectionProbe ue4ss_import)
target_link_libraries(FFRSelectionProbe PRIVATE bridge_core "${GENERATED}/UE4SS.lib")
target_include_directories(FFRSelectionProbe SYSTEM PRIVATE "${GENERATED}/include" "${SDK}/UE4SS/include"
  "${SDK}/deps/first/LuaMadeSimple/include" "${SDK}/deps/first/LuaRaw/include"
  "${SDK}/deps/first/File/include" "${SDK}/deps/first/Input/include" "${SDK}/deps/first/String/include"
  "${DEPS}/fmt-11.2.0/include")
target_compile_definitions(FFRSelectionProbe PRIVATE HAS_INPUT _DISABLE_CONSTEXPR_MUTEX_CONSTRUCTOR)
target_compile_options(FFRSelectionProbe PRIVATE /W4 /EHsc /utf-8)
set_target_properties(FFRSelectionProbe PROPERTIES OUTPUT_NAME main)
