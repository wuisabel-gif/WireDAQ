# WireDAQ — C/C++ codec library.
#
# Builds the wire-format codec (the C source under firmware/codec/) as a library that
# C and C++ projects can link, with an idiomatic C++ wrapper header. The library is
# held to the same golden vectors as the Python codec (see the CTest below).
#
#   cmake -S . -B build
#   cmake --build build
#   ctest --test-dir build --output-on-failure
#   cmake --install build --prefix /path/to/prefix
#
# Consume it from another CMake project:
#   find_package(WireDAQ CONFIG REQUIRED)
#   target_link_libraries(my_app PRIVATE wiredaq::codec)   # then #include <wiredaq/wiredaq.hpp>

cmake_minimum_required(VERSION 3.16)
project(WireDAQ VERSION 0.1.0 LANGUAGES C CXX)

option(WIREDAQ_BUILD_TESTS "Build the WireDAQ conformance tests" ON)
option(WIREDAQ_BUILD_EXAMPLES "Build the WireDAQ examples" ON)

include(GNUInstallDirs)

# --- the codec library -------------------------------------------------------
# C source compiled as C11; the public surface includes the C header and the
# header-only C++17 wrapper, so consumers get cxx_std_17 as an interface requirement.
add_library(wiredaq_codec firmware/codec/wiredaq_codec.c)
add_library(wiredaq::codec ALIAS wiredaq_codec)

set_target_properties(wiredaq_codec PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED ON
    EXPORT_NAME codec          # exported/imported as wiredaq::codec (matches the alias)
    VERSION ${PROJECT_VERSION}
    SOVERSION ${PROJECT_VERSION_MAJOR})

target_compile_features(wiredaq_codec INTERFACE cxx_std_17)

target_include_directories(wiredaq_codec PUBLIC
    "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/firmware/codec>"
    "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>"
    "$<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>")

# --- install + export so find_package(WireDAQ) works -------------------------
install(TARGETS wiredaq_codec EXPORT WireDAQTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})

install(FILES firmware/codec/wiredaq_codec.h
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})
install(FILES include/wiredaq/wiredaq.hpp
    DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/wiredaq)

install(EXPORT WireDAQTargets
    FILE WireDAQTargets.cmake
    NAMESPACE wiredaq::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/WireDAQ)

include(CMakePackageConfigHelpers)
configure_package_config_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/cmake/WireDAQConfig.cmake.in"
    "${CMAKE_CURRENT_BINARY_DIR}/WireDAQConfig.cmake"
    INSTALL_DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/WireDAQ)
write_basic_package_version_file(
    "${CMAKE_CURRENT_BINARY_DIR}/WireDAQConfigVersion.cmake"
    VERSION ${PROJECT_VERSION}
    COMPATIBILITY SameMajorVersion)
install(FILES
    "${CMAKE_CURRENT_BINARY_DIR}/WireDAQConfig.cmake"
    "${CMAKE_CURRENT_BINARY_DIR}/WireDAQConfigVersion.cmake"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/WireDAQ)

# --- examples ----------------------------------------------------------------
if(WIREDAQ_BUILD_EXAMPLES)
    add_executable(wiredaq_example examples/encode_decode.cpp)
    target_link_libraries(wiredaq_example PRIVATE wiredaq::codec)
endif()

# --- tests: same golden vectors as the Python codec --------------------------
if(WIREDAQ_BUILD_TESTS)
    enable_testing()
    find_package(Python3 COMPONENTS Interpreter REQUIRED)

    # Regenerate the golden header from vectors.json (the single source of truth).
    set(WIREDAQ_GOLDEN_HDR "${CMAKE_CURRENT_SOURCE_DIR}/firmware/test/golden_vectors.h")
    add_custom_command(
        OUTPUT "${WIREDAQ_GOLDEN_HDR}"
        COMMAND ${Python3_EXECUTABLE}
                "${CMAKE_CURRENT_SOURCE_DIR}/firmware/test/gen_golden_header.py"
        DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/firmware/test/gen_golden_header.py"
                "${CMAKE_CURRENT_SOURCE_DIR}/src/wiredaq/protocol/golden/vectors.json"
        COMMENT "Generating golden_vectors.h from vectors.json")
    add_custom_target(wiredaq_golden_header DEPENDS "${WIREDAQ_GOLDEN_HDR}")

    add_executable(wiredaq_test_codec cpp/test/test_codec.cpp)
    add_dependencies(wiredaq_test_codec wiredaq_golden_header)
    target_link_libraries(wiredaq_test_codec PRIVATE wiredaq::codec)
    target_include_directories(wiredaq_test_codec PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/firmware/test")
    add_test(NAME cpp_golden_vectors COMMAND wiredaq_test_codec)
endif()
