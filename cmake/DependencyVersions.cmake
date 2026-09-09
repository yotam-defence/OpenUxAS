# ============================================================================
# DependencyVersions.cmake -- Single source of truth for dependency versions
# ============================================================================
#
# All third-party dependency version pins live here so they can be reviewed,
# audited, and bumped in one place.  Other CMake modules (Dependencies.cmake,
# BuildSerial.cmake) include this file and reference the variables below.
# ============================================================================

# Independent dependencies
set(DEP_BOOST_VERSION    "1.85.0")
set(DEP_BOOST_URL_HASH   "SHA256=0a9cc56ceae46986f5f4d43fe0311d90cf6d2fa9028258a95cab49ffdacf92ad")
set(DEP_PUGIXML_TAG      "v1.14")
set(DEP_SQLITECPP_TAG    "3.3.2")
set(DEP_SERIAL_TAG       "1.2.1")

# ZeroMQ stack
set(DEP_LIBZMQ_TAG       "v4.3.5")
set(DEP_CPPZMQ_TAG       "v4.10.0")
set(DEP_CZMQ_TAG         "v4.2.1")
set(DEP_ZYRE_TAG         "v2.0.1")
