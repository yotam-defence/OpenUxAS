# ============================================================================
# LmcpGeneration.cmake -- LMCP C++ code generation and library target
# ============================================================================
#
# The LMCP (Lightweight Message Construction Protocol) layer provides the
# auto-generated message classes consumed by every OpenUxAS module.  The
# generation step:
#   1. Builds LmcpGen.jar from the sibling LmcpGen repository (if needed).
#   2. Invokes `java -jar LmcpGen.jar` on the MDM XML definitions to produce
#      a tree of C++ headers and sources under ${LMCP_DIR}.
#   3. Includes the generated CMakeLists.txt (produced by LmcpGen) which
#      defines the `lmcp` STATIC library target.
#
# Both the LmcpGen build and the code generation happen at *configure* time
# via execute_process() so that the generated source list is available to
# CMake for proper dependency tracking.
# ============================================================================

# ---------------------------------------------------------------------------
# Configurable paths (overridable via -D on the cmake command line)
# ---------------------------------------------------------------------------

# Path to the LmcpGen repository (contains gradlew and build.gradle.kts)
set(LMCPGEN_DIR "${CMAKE_SOURCE_DIR}/../LmcpGen"
    CACHE PATH "Path to the LmcpGen repository")

# Directory where generated LMCP C++ code lives (gitignored)
set(LMCP_DIR "${CMAKE_SOURCE_DIR}/src/cpp/LMCP"
    CACHE PATH "Output directory for generated LMCP C++ sources")

# Directory containing MDM XML definitions
set(MDMS_DIR "${CMAKE_SOURCE_DIR}/mdms"
    CACHE PATH "Directory containing MDM XML files")

# Path to the Java executable
find_program(Java_EXECUTABLE java
    HINTS ENV JAVA_HOME
    PATH_SUFFIXES bin
    DOC "Path to the Java runtime"
)
if(NOT Java_EXECUTABLE)
    message(FATAL_ERROR
        "Java not found. LmcpGen requires Java to generate LMCP C++ code.\n"
        "Install a JDK (>= 11) or set -DJava_EXECUTABLE=/path/to/java")
endif()

# ---------------------------------------------------------------------------
# Resolve LMCPGEN_DIR to an absolute path
# ---------------------------------------------------------------------------
get_filename_component(LMCPGEN_DIR "${LMCPGEN_DIR}" ABSOLUTE)

if(NOT EXISTS "${LMCPGEN_DIR}/gradlew")
    message(FATAL_ERROR
        "LmcpGen repository not found at ${LMCPGEN_DIR}\n"
        "Expected to find gradlew in the LmcpGen directory.\n"
        "Set -DLMCPGEN_DIR=/path/to/LmcpGen to override.")
endif()

# ---------------------------------------------------------------------------
# Step 1: Build LmcpGen.jar (if not already present)
# ---------------------------------------------------------------------------
set(LMCPGEN_JAR "${LMCPGEN_DIR}/build/libs/LmcpGen.jar")

if(NOT EXISTS "${LMCPGEN_JAR}")
    message(STATUS "LmcpGen.jar not found -- building via Gradle...")
    execute_process(
        COMMAND "${LMCPGEN_DIR}/gradlew" jar
        WORKING_DIRECTORY "${LMCPGEN_DIR}"
        RESULT_VARIABLE _gradle_result
        OUTPUT_VARIABLE _gradle_output
        ERROR_VARIABLE  _gradle_error
    )
    if(NOT _gradle_result EQUAL 0)
        message(FATAL_ERROR
            "Failed to build LmcpGen.jar via Gradle (exit code ${_gradle_result}).\n"
            "Gradle output:\n${_gradle_output}\n"
            "Gradle errors:\n${_gradle_error}")
    endif()
    if(NOT EXISTS "${LMCPGEN_JAR}")
        message(FATAL_ERROR
            "Gradle succeeded but LmcpGen.jar was not produced at ${LMCPGEN_JAR}")
    endif()
    message(STATUS "LmcpGen.jar built successfully: ${LMCPGEN_JAR}")
else()
    message(STATUS "Using existing LmcpGen.jar: ${LMCPGEN_JAR}")
endif()

# ---------------------------------------------------------------------------
# Step 2: Generate LMCP C++ code from MDM XML files
# ---------------------------------------------------------------------------
# We use a stamp file to avoid re-running generation on every configure.
# The stamp is invalidated if any MDM file is newer than the stamp.
set(_lmcp_stamp "${LMCP_DIR}/.lmcp_generated_stamp")
set(_need_generation FALSE)

if(NOT EXISTS "${_lmcp_stamp}")
    set(_need_generation TRUE)
    set(_generation_reason "no stamp file found (first generation)")
else()
    # Check if any MDM file is newer than the stamp
    file(GLOB _mdm_files "${MDMS_DIR}/*.xml")
    foreach(_mdm IN LISTS _mdm_files)
        if("${_mdm}" IS_NEWER_THAN "${_lmcp_stamp}")
            set(_need_generation TRUE)
            set(_generation_reason "${_mdm} is newer than stamp")
            break()
        endif()
    endforeach()
    # Also check if LmcpGen.jar is newer than the stamp
    if(NOT _need_generation AND "${LMCPGEN_JAR}" IS_NEWER_THAN "${_lmcp_stamp}")
        set(_need_generation TRUE)
        set(_generation_reason "LmcpGen.jar is newer than stamp")
    endif()
endif()

if(_need_generation)
    message(STATUS "Generating LMCP C++ code (${_generation_reason})...")
    message(STATUS "  MDM directory: ${MDMS_DIR}")
    message(STATUS "  Output directory: ${LMCP_DIR}")

    # Ensure output directory exists
    file(MAKE_DIRECTORY "${LMCP_DIR}")

    execute_process(
        COMMAND "${Java_EXECUTABLE}" -Xmx2048m
                -jar "${LMCPGEN_JAR}"
                -mdmdir "${MDMS_DIR}"
                -cpp
                -dir "${LMCP_DIR}"
        WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
        RESULT_VARIABLE _lmcpgen_result
        OUTPUT_VARIABLE _lmcpgen_output
        ERROR_VARIABLE  _lmcpgen_error
    )
    if(NOT _lmcpgen_result EQUAL 0)
        message(FATAL_ERROR
            "LMCP code generation failed (exit code ${_lmcpgen_result}).\n"
            "LmcpGen output:\n${_lmcpgen_output}\n"
            "LmcpGen errors:\n${_lmcpgen_error}")
    endif()

    # Verify the generated CMakeLists.txt exists
    if(NOT EXISTS "${LMCP_DIR}/CMakeLists.txt")
        message(FATAL_ERROR
            "LMCP code generation completed but no CMakeLists.txt was produced "
            "at ${LMCP_DIR}/CMakeLists.txt")
    endif()

    # Write stamp file
    string(TIMESTAMP _stamp_time "%Y-%m-%dT%H:%M:%S")
    file(WRITE "${_lmcp_stamp}"
        "LMCP code generated at ${_stamp_time}\n"
        "LmcpGen.jar: ${LMCPGEN_JAR}\n"
        "MDM directory: ${MDMS_DIR}\n")

    message(STATUS "LMCP C++ code generated successfully.")
else()
    message(STATUS "LMCP C++ code is up to date (skipping generation).")
endif()

# ---------------------------------------------------------------------------
# Step 3: Include the generated LMCP library
# ---------------------------------------------------------------------------
# LmcpGen produces a CMakeLists.txt that defines the `lmcp` STATIC library
# with the full source listing, platform-specific definitions, and include
# directories.  We include it via add_subdirectory().
#
# The generated CMakeLists.txt uses cmake_minimum_required(VERSION 3.0) and
# project(LMCP).  This is fine as a sub-project; CMake handles the version
# mismatch gracefully.
add_subdirectory("${LMCP_DIR}" "${CMAKE_BINARY_DIR}/lmcp")

# ---------------------------------------------------------------------------
# Custom target for explicit regeneration
# ---------------------------------------------------------------------------
# Users can run `cmake --build build --target lmcp_generate` to force
# regeneration.  This is useful during development when MDM files change
# and you want to regenerate without a full reconfigure.
add_custom_target(lmcp_generate
    COMMAND "${Java_EXECUTABLE}" -Xmx2048m
            -jar "${LMCPGEN_JAR}"
            -mdmdir "${MDMS_DIR}"
            -cpp
            -dir "${LMCP_DIR}"
    WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
    COMMENT "Regenerating LMCP C++ code from MDM XML definitions"
    VERBATIM
)
