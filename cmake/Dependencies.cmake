# ============================================================================
# Dependencies.cmake -- FetchContent declarations for OpenUxAS third-parties
# ============================================================================
#
# Every dependency is fetched once via FetchContent at configure time.  Build
# options for each dependency are set *before* FetchContent_MakeAvailable so
# they take effect in the sub-build.
#
# The ZeroMQ stack (libzmq -> czmq -> zyre) must be staged: each layer's
# find_package() expects the previous layer to be installed.  We work around
# this by populating the LIBZMQ_*/CZMQ_* cache variables from the
# FetchContent-built targets before the next layer configures.
#
# Version pins are centralized in DependencyVersions.cmake.

include(cmake/DependencyVersions.cmake)
# ============================================================================

include(FetchContent)

macro(exclude_targets_from_all)
    foreach(_target ${ARGN})
        if(TARGET ${_target})
            set_target_properties(${_target} PROPERTIES EXCLUDE_FROM_ALL TRUE)
        endif()
    endforeach()
endmacro()

# ===========================================================================
# Independent dependencies (no ordering constraints among these)
# ===========================================================================

# ---------------------------------------------------------------------------
# Boost  (fetched from the CMake-ready release tarball because cloning the
#         full Boost super-repo is impractically large)
# ---------------------------------------------------------------------------
set(BOOST_INCLUDE_LIBRARIES
    filesystem
    regex
    date_time
    system
    geometry
    graph
    polygon
    property_map
    tokenizer
    algorithm
    bimap
    container_hash
    uuid
)

FetchContent_Declare(
    Boost
    URL      https://github.com/boostorg/boost/releases/download/boost-${DEP_BOOST_VERSION}/boost-${DEP_BOOST_VERSION}-cmake.tar.xz
    URL_HASH ${DEP_BOOST_URL_HASH}
)

# ---------------------------------------------------------------------------
# pugixml  (lightweight XML parser)
# ---------------------------------------------------------------------------
FetchContent_Declare(
    pugixml
    GIT_REPOSITORY https://github.com/zeux/pugixml.git
    GIT_TAG        ${DEP_PUGIXML_TAG}
    GIT_SHALLOW    TRUE
)

# ---------------------------------------------------------------------------
# SQLiteCpp  (C++ wrapper around SQLite3)
# ---------------------------------------------------------------------------
set(SQLITECPP_RUN_CPPLINT     OFF CACHE BOOL "" FORCE)
set(SQLITECPP_RUN_CPPCHECK    OFF CACHE BOOL "" FORCE)
set(SQLITECPP_INTERNAL_SQLITE ON  CACHE BOOL "" FORCE)
set(SQLITE_ENABLE_COLUMN_METADATA OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    SQLiteCpp
    GIT_REPOSITORY https://github.com/SRombauts/SQLiteCpp.git
    GIT_TAG        ${DEP_SQLITECPP_TAG}
    GIT_SHALLOW    TRUE
)

# ---------------------------------------------------------------------------
# Independent deps -- make available in one pass
# ---------------------------------------------------------------------------
FetchContent_MakeAvailable(
    Boost
    pugixml
    SQLiteCpp
)

# ---------------------------------------------------------------------------
# serial  (cross-platform serial port library)
# ---------------------------------------------------------------------------
# Built via a custom module because the upstream CMakeLists.txt requires ROS
# catkin which is not available in this project.
include(cmake/BuildSerial.cmake)

# ===========================================================================
# ZeroMQ stack -- must be staged because each layer's CMakeLists.txt calls
# find_package() for the layer below it.
# ===========================================================================

# ---------------------------------------------------------------------------
# 1. libzmq  (ZeroMQ core library)
# ---------------------------------------------------------------------------
set(ZMQ_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(BUILD_TESTS     OFF CACHE BOOL "" FORCE)
set(BUILD_SHARED    OFF CACHE BOOL "" FORCE)
set(BUILD_STATIC    ON  CACHE BOOL "" FORCE)
set(WITH_DOCS       OFF CACHE BOOL "" FORCE)
set(WITH_PERF_TOOL  OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    libzmq
    GIT_REPOSITORY https://github.com/zeromq/libzmq.git
    GIT_TAG        ${DEP_LIBZMQ_TAG}
    GIT_SHALLOW    TRUE
)

FetchContent_MakeAvailable(libzmq)

# Exclude libzmq executables from default build (they are not needed)
exclude_targets_from_all(curve_keygen)

# Expose libzmq to CZMQ's Findlibzmq.cmake via cache variables.
# libzmq's CMake build creates the 'libzmq-static' target.
FetchContent_GetProperties(libzmq SOURCE_DIR LIBZMQ_SOURCE_DIR)
set(LIBZMQ_INCLUDE_DIRS "${LIBZMQ_SOURCE_DIR}/include" CACHE PATH "" FORCE)
set(LIBZMQ_LIBRARIES    libzmq-static                  CACHE STRING "" FORCE)
set(LIBZMQ_FOUND        TRUE                           CACHE BOOL "" FORCE)

# ---------------------------------------------------------------------------
# 2. cppzmq  (C++ header-only binding for libzmq)
# ---------------------------------------------------------------------------
set(CPPZMQ_BUILD_TESTS OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
    cppzmq
    GIT_REPOSITORY https://github.com/zeromq/cppzmq.git
    GIT_TAG        ${DEP_CPPZMQ_TAG}
    GIT_SHALLOW    TRUE
)

FetchContent_MakeAvailable(cppzmq)

# ---------------------------------------------------------------------------
# 3. CZMQ  (high-level C binding for ZeroMQ)
# ---------------------------------------------------------------------------
set(CZMQ_BUILD_TESTS   OFF CACHE BOOL "" FORCE)
set(CZMQ_BUILD_SHARED  OFF CACHE BOOL "" FORCE)
set(CZMQ_BUILD_STATIC  ON  CACHE BOOL "" FORCE)

FetchContent_Declare(
    czmq
    GIT_REPOSITORY https://github.com/zeromq/czmq.git
    GIT_TAG        ${DEP_CZMQ_TAG}
    GIT_SHALLOW    TRUE
)

FetchContent_MakeAvailable(czmq)

# Exclude CZMQ executables/tests from default build
exclude_targets_from_all(czmq_selftest zmakecert zsp test_randof)

# Expose CZMQ to Zyre's Findczmq.cmake via cache variables.
FetchContent_GetProperties(czmq SOURCE_DIR CZMQ_SOURCE_DIR)
set(CZMQ_INCLUDE_DIRS "${CZMQ_SOURCE_DIR}/include" CACHE PATH "" FORCE)
set(CZMQ_LIBRARIES    czmq-static                  CACHE STRING "" FORCE)
set(CZMQ_FOUND        TRUE                         CACHE BOOL "" FORCE)

# ---------------------------------------------------------------------------
# 4. Zyre  (clustering library on top of ZeroMQ)
# ---------------------------------------------------------------------------
set(ZYRE_BUILD_TESTS  OFF CACHE BOOL "" FORCE)
set(ZYRE_BUILD_SHARED OFF CACHE BOOL "" FORCE)
set(ZYRE_BUILD_STATIC ON  CACHE BOOL "" FORCE)

FetchContent_Declare(
    zyre
    GIT_REPOSITORY https://github.com/zeromq/zyre.git
    GIT_TAG        ${DEP_ZYRE_TAG}
    GIT_SHALLOW    TRUE
)

FetchContent_MakeAvailable(zyre)

# Exclude Zyre example/tool/test executables from default build.
# These fail to link due to duplicate sha1 symbols between libzmq and czmq
# static archives — and they are not needed by OpenUxAS.
exclude_targets_from_all(chat perf_local perf_remote zpinger ztester_beacon ztester_gossip zyre_selftest)
