# ============================================================================
# OpenUxAS -- Top-level CMake build
# ============================================================================
#
# Build:
#   cmake -B build -DCMAKE_BUILD_TYPE=Release
#   cmake --build build -j$(nproc)
#
# NOTE: LMCP code generation (Task 3) must complete before a full build will
#       succeed.  `cmake -B build` should configure without errors even before
#       that step is done.
# ============================================================================

cmake_minimum_required(VERSION 3.22)

project(OpenUxAS
    VERSION   3.2.0
    LANGUAGES CXX
)

# ---- C++ standard (C++11 for this milestone; future milestones upgrade) ----
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# ---- Position-independent code (matches -fPIC in the old Makefile) ---------
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ---- Compile definitions (suppress Boost deprecation warnings) -------------
add_compile_definitions(
    BOOST_ALLOW_DEPRECATED_HEADERS
    BOOST_GEOMETRY_DISABLE_DEPRECATED_03_WARNING
)

# ---- Export compile_commands.json for tooling (clangd, IDEs) ---------------
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ---- Optional flags carried over from the old Makefile ---------------------
option(ENABLE_WARNINGS  "Enable -Wall for the build"                    OFF)
option(ENABLE_COVERAGE  "Build with gcov instrumentation (GCOV_MODE=1)" OFF)

if(ENABLE_WARNINGS)
    add_compile_options(-Wall)
endif()

if(ENABLE_COVERAGE)
    add_compile_options(-fprofile-arcs -ftest-coverage)
    add_compile_definitions(GCOV_MODE=1)
    add_link_options(-fprofile-arcs -ftest-coverage)
endif()

# ---- CMake module path -----------------------------------------------------
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")

# ---- Third-party dependencies (FetchContent) -------------------------------
include(cmake/Dependencies.cmake)

# ---- LMCP code-generation placeholder (completed by Task 3) ---------------
include(cmake/LmcpGeneration.cmake)

# ---- Source tree -----------------------------------------------------------
add_subdirectory(src/cpp)
