cmake_minimum_required(VERSION 3.10)
project(my_lib_parser LANGUAGES CXX)


set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(CMAKE_POSITION_INDEPENDENT_CODE ON)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# Find pybind11 (must be installed)
# If not found, you can manually include it using add_subdirectory(pybind11)
find_package(pybind11 REQUIRED)

include_directories(${CMAKE_CURRENT_SOURCE_DIR})

# Declare si2dr_liberty as an IMPORTED static library
add_library(si2dr_liberty STATIC IMPORTED)
set_target_properties(si2dr_liberty PROPERTIES
    IMPORTED_LOCATION "${CMAKE_CURRENT_SOURCE_DIR}/libsi2dr_liberty.a"
)


pybind11_add_module(liberty_api
    python_binding.cpp
    lib_parser_api.cpp
    lib_modify_api.cpp
)

# Link with si2dr_liberty static library 
target_link_libraries(liberty_api PRIVATE si2dr_liberty)

