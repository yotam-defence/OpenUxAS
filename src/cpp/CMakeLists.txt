# ============================================================================
# src/cpp/CMakeLists.txt -- OpenUxAS C++ source tree
# ============================================================================
#
# Defines per-module STATIC library targets and the final `uxas` executable.
#
# The original codebase has a flat include structure: every source directory
# is added as -I and modules freely include headers from each other (including
# circular dependencies such as Services <-> Tasks).  We replicate this by
# creating an INTERFACE library (uxas_common_includes) that gathers all
# module include directories and third-party header dependencies.  Every
# STATIC library target links to it so that compilation succeeds regardless
# of cross-module include direction.
# ============================================================================

set(UXAS_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}")

# ============================================================================
# uxas_common_includes -- flat include path umbrella (INTERFACE)
# ============================================================================
# Mirrors the old Makefile's -I$(SOURCE_DIR)/Communications -I... for every
# source directory.  Also carries the third-party header-only dependencies
# that are referenced across many modules (Boost, pugixml, ZMQ, etc.).
# ============================================================================

add_library(uxas_common_includes INTERFACE)

target_include_directories(uxas_common_includes INTERFACE
    # --- project module directories ---
    "${UXAS_SRC_DIR}/Includes"
    "${UXAS_SRC_DIR}/Includes/Constants"
    "${UXAS_SRC_DIR}/Includes/TypeDefs"
    "${UXAS_SRC_DIR}/Communications"
    "${UXAS_SRC_DIR}/Communications/ZeroMq"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/Proxy"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/Receivers"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/Senders"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/Sockets"
    "${UXAS_SRC_DIR}/DPSS"
    "${UXAS_SRC_DIR}/Plans"
    "${UXAS_SRC_DIR}/Services"
    "${UXAS_SRC_DIR}/Tasks"
    "${UXAS_SRC_DIR}/Utilities"
    "${UXAS_SRC_DIR}/VisilibityLib"
)

# Third-party header dependencies used across multiple modules.
target_link_libraries(uxas_common_includes INTERFACE
    lmcp
    Boost::filesystem
    Boost::regex
    Boost::date_time
    Boost::system
    Boost::geometry
    Boost::graph
    Boost::polygon
    pugixml::pugixml
    SQLiteCpp
    cppzmq-static
    serial
)

# ============================================================================
# uxas_visilibity -- Visibility algorithms
# ============================================================================
file(GLOB VISILIBITY_SOURCES
    "${UXAS_SRC_DIR}/VisilibityLib/*.cpp"
    "${UXAS_SRC_DIR}/VisilibityLib/*.h"
)

add_library(uxas_visilibity STATIC ${VISILIBITY_SOURCES})
target_include_directories(uxas_visilibity PUBLIC
    "${UXAS_SRC_DIR}/VisilibityLib"
)
target_link_libraries(uxas_visilibity PUBLIC uxas_common_includes)

# ============================================================================
# uxas_plans -- Planning data structures
# ============================================================================
file(GLOB PLANS_SOURCES
    "${UXAS_SRC_DIR}/Plans/*.cpp"
    "${UXAS_SRC_DIR}/Plans/*.h"
)

add_library(uxas_plans STATIC ${PLANS_SOURCES})
target_include_directories(uxas_plans PUBLIC
    "${UXAS_SRC_DIR}/Plans"
)
target_link_libraries(uxas_plans PUBLIC uxas_common_includes)

# ============================================================================
# uxas_dpss -- DPSS (path/sensor steering algorithms)
# ============================================================================
file(GLOB DPSS_SOURCES
    "${UXAS_SRC_DIR}/DPSS/*.cpp"
    "${UXAS_SRC_DIR}/DPSS/*.h"
)

add_library(uxas_dpss STATIC ${DPSS_SOURCES})
target_include_directories(uxas_dpss PUBLIC
    "${UXAS_SRC_DIR}/DPSS"
)
target_link_libraries(uxas_dpss PUBLIC uxas_common_includes)

# ============================================================================
# uxas_utilities -- Logging, config, math, XML, etc.
# ============================================================================
# Collect sources from Utilities/ but EXCLUDE the localcoords/ subdirectory
# which is a Python C extension module, not a regular UxAS C++ source.
file(GLOB UTILITIES_SOURCES
    "${UXAS_SRC_DIR}/Utilities/*.cpp"
    "${UXAS_SRC_DIR}/Utilities/*.h"
)

add_library(uxas_utilities STATIC ${UTILITIES_SOURCES})
target_include_directories(uxas_utilities PUBLIC
    "${UXAS_SRC_DIR}/Utilities"
)
target_link_libraries(uxas_utilities PUBLIC uxas_common_includes)

# ============================================================================
# uxas_communications -- ZeroMQ messaging layer
# ============================================================================
# Collect from Communications/ and all ZeroMq/** subdirectories.
file(GLOB COMMS_TOP_SOURCES
    "${UXAS_SRC_DIR}/Communications/*.cpp"
    "${UXAS_SRC_DIR}/Communications/*.h"
)
file(GLOB_RECURSE COMMS_ZMQ_SOURCES
    "${UXAS_SRC_DIR}/Communications/ZeroMq/*.cpp"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/*.h"
)

add_library(uxas_communications STATIC
    ${COMMS_TOP_SOURCES}
    ${COMMS_ZMQ_SOURCES}
)
target_include_directories(uxas_communications PUBLIC
    "${UXAS_SRC_DIR}/Communications"
    "${UXAS_SRC_DIR}/Communications/ZeroMq"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/Proxy"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/Receivers"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/Senders"
    "${UXAS_SRC_DIR}/Communications/ZeroMq/Sockets"
)
target_link_libraries(uxas_communications
    PUBLIC  uxas_common_includes
            czmq-static
            zyre-static
)

# ============================================================================
# uxas_services -- ~35 service implementations
# ============================================================================
file(GLOB SERVICES_SOURCES
    "${UXAS_SRC_DIR}/Services/*.cpp"
    "${UXAS_SRC_DIR}/Services/*.h"
)

add_library(uxas_services STATIC ${SERVICES_SOURCES})
target_include_directories(uxas_services PUBLIC
    "${UXAS_SRC_DIR}/Services"
    "${CMAKE_SOURCE_DIR}/resources/AutomationDiagramDataService"
)
target_link_libraries(uxas_services PUBLIC uxas_common_includes)

# ============================================================================
# uxas_tasks -- ~20 task implementations
# ============================================================================
file(GLOB TASKS_SOURCES
    "${UXAS_SRC_DIR}/Tasks/*.cpp"
    "${UXAS_SRC_DIR}/Tasks/*.h"
)

add_library(uxas_tasks STATIC ${TASKS_SOURCES})
target_include_directories(uxas_tasks PUBLIC
    "${UXAS_SRC_DIR}/Tasks"
)
target_link_libraries(uxas_tasks PUBLIC uxas_common_includes)

# ============================================================================
# uxas -- Main executable
# ============================================================================
add_executable(uxas "${UXAS_SRC_DIR}/UxAS_Main.cpp")

# GNU ld (Linux) requires explicit linker groups to resolve circular
# dependencies between services, tasks, and communications.
# Apple ld64 and other non-GNU linkers handle this automatically.
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_link_libraries(uxas
        PRIVATE
            -Wl,--start-group
                uxas_tasks
                uxas_services
                uxas_communications
                uxas_utilities
            -Wl,--end-group
            uxas_plans
            uxas_dpss
            uxas_visilibity
            uxas_common_includes
            czmq-static
            zyre-static
    )
else()
    target_link_libraries(uxas
        PRIVATE
            uxas_tasks
            uxas_services
            uxas_communications
            uxas_utilities
            uxas_plans
            uxas_dpss
            uxas_visilibity
            uxas_common_includes
            czmq-static
            zyre-static
    )
endif()

# System libraries (matching the old Makefile's linker flags)
if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_link_libraries(uxas PRIVATE uuid dl pthread)
    target_link_options(uxas PRIVATE -static-libstdc++ -static-libgcc)
endif()
