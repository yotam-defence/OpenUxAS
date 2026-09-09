# ============================================================================
# LmcpGeneration.cmake -- LMCP C++ code generation and library target
# ============================================================================
#
# The LMCP (Lightweight Message Construction Protocol) layer provides the
# auto-generated message classes consumed by every OpenUxAS module.  The
# generation step invokes LmcpGen.jar on the MDM XML definitions and produces
# a tree of C++ headers and sources under ${LMCP_DIR}.
#
# Task 3 will complete this module by:
#   1. Building LmcpGen.jar from the sibling LmcpGen repository.
#   2. Invoking `java -jar LmcpGen.jar` via add_custom_command to generate
#      the C++ sources.
#   3. Populating the `lmcp` library target with the generated files.
#
# For now we define the output directory, the INTERFACE library target (so
# downstream targets can already express their dependency on lmcp), and the
# placeholder custom target that Task 3 will replace.
# ============================================================================

# Directory where generated LMCP C++ code lives (gitignored)
set(LMCP_DIR "${CMAKE_SOURCE_DIR}/src/cpp/LMCP")

# ---------------------------------------------------------------------------
# Placeholder: LMCP generation custom target
# ---------------------------------------------------------------------------
# Task 3 will replace this with add_custom_command / add_custom_target that
# actually invokes LmcpGen.jar.  For now we just define a target so the rest
# of the build graph can depend on it.
if(NOT TARGET lmcp_generate)
    add_custom_target(lmcp_generate
        COMMENT "LMCP generation placeholder -- Task 3 will complete this step"
    )
endif()

# ---------------------------------------------------------------------------
# lmcp library target
# ---------------------------------------------------------------------------
# We use an INTERFACE library for now because no generated sources exist yet.
# Task 3 will convert this to a STATIC library once the generated file list
# is known (via file(GLOB_RECURSE ...)).
#
# All modules include LMCP headers with bare paths such as:
#     #include "afrl/cmasi/AirVehicleState.h"
# so the include root must be ${LMCP_DIR}.
if(NOT TARGET lmcp)
    add_library(lmcp INTERFACE)
    add_dependencies(lmcp lmcp_generate)

    # The LMCP directory may not exist yet (it is gitignored and generated).
    # INTERFACE include directories are only consumed at *build* time, and the
    # directory will exist by then (after lmcp_generate runs).  We guard with
    # a generator expression so CMake does not warn at configure time.
    target_include_directories(lmcp INTERFACE
        $<BUILD_INTERFACE:${LMCP_DIR}>
    )
endif()
