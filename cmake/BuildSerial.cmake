# ============================================================================
# BuildSerial.cmake -- Build the wjwwood/serial library without catkin
# ============================================================================
#
# The upstream serial library is a ROS catkin package whose CMakeLists.txt
# requires find_package(catkin).  Since OpenUxAS does not use ROS we fetch
# the sources and build a plain STATIC library target directly.
# ============================================================================

include(FetchContent)

FetchContent_Declare(
    serial
    GIT_REPOSITORY https://github.com/wjwwood/serial.git
    GIT_TAG        1.2.1
    GIT_SHALLOW    TRUE
)

# Populate sources only -- do NOT call FetchContent_MakeAvailable because
# the upstream CMakeLists.txt requires catkin.
FetchContent_GetProperties(serial)
if(NOT serial_POPULATED)
    FetchContent_Populate(serial)
endif()

set(SERIAL_SOURCES
    "${serial_SOURCE_DIR}/src/serial.cc"
    "${serial_SOURCE_DIR}/include/serial/serial.h"
    "${serial_SOURCE_DIR}/include/serial/v8stdint.h"
)

if(APPLE)
    list(APPEND SERIAL_SOURCES
        "${serial_SOURCE_DIR}/src/impl/unix.cc"
        "${serial_SOURCE_DIR}/src/impl/list_ports/list_ports_osx.cc"
    )
elseif(UNIX)
    list(APPEND SERIAL_SOURCES
        "${serial_SOURCE_DIR}/src/impl/unix.cc"
        "${serial_SOURCE_DIR}/src/impl/list_ports/list_ports_linux.cc"
    )
else()
    list(APPEND SERIAL_SOURCES
        "${serial_SOURCE_DIR}/src/impl/win.cc"
        "${serial_SOURCE_DIR}/src/impl/list_ports/list_ports_win.cc"
    )
endif()

add_library(serial STATIC ${SERIAL_SOURCES})

target_include_directories(serial PUBLIC
    "${serial_SOURCE_DIR}/include"
)

if(APPLE)
    find_library(IOKIT_LIBRARY IOKit)
    find_library(FOUNDATION_LIBRARY Foundation)
    target_link_libraries(serial PUBLIC ${FOUNDATION_LIBRARY} ${IOKIT_LIBRARY})
elseif(UNIX)
    target_link_libraries(serial PUBLIC rt pthread)
else()
    target_link_libraries(serial PUBLIC setupapi)
endif()
