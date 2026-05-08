cmake_minimum_required(VERSION 3.20)
project(port_tariff_core CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

include(FetchContent)
FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG v3.11.3
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(nlohmann_json)

add_executable(port_tariff_core
    core/src/main.cpp
    core/src/CoreCli.cpp
    core/src/DocumentClassifier.cpp
    core/src/FormulaEvaluator.cpp
    core/src/JsonUtil.cpp
    core/src/PlanGraph.cpp
    core/src/PromptBuilder.cpp
    core/src/RuleMatcher.cpp
    core/src/TariffEngine.cpp)

target_link_libraries(port_tariff_core PRIVATE nlohmann_json::nlohmann_json)
target_include_directories(port_tariff_core PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/core/include)
