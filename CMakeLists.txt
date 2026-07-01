cmake_minimum_required(VERSION 3.16)
project(damov2 LANGUAGES CXX VERSION 2.0.0
        DESCRIPTION "Modern data-movement bottleneck analysis (gem5 + Ramulator2)")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

add_compile_options(-Wall -Wextra)

# ---- Core library: the DAMOV methodology, simulator-independent ------------
add_library(damov_core STATIC
    src/trace/trace.cpp
    src/locality/locality.cpp
    src/metrics/metrics.cpp
    src/classify/classify.cpp)
target_include_directories(damov_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

# ---- CLI tools -------------------------------------------------------------
add_executable(damov-locality src/cli/damov_locality.cpp)
target_link_libraries(damov-locality PRIVATE damov_core)

add_executable(damov-stats src/cli/damov_stats.cpp)
target_link_libraries(damov-stats PRIVATE damov_core)

add_executable(damov-classify src/cli/damov_classify.cpp)
target_link_libraries(damov-classify PRIVATE damov_core)

install(TARGETS damov-locality damov-stats damov-classify RUNTIME DESTINATION bin)
install(DIRECTORY include/damov DESTINATION include)
install(FILES hooks/damov_hooks.h DESTINATION include)

# ---- Tests -----------------------------------------------------------------
enable_testing()
add_subdirectory(tests)
