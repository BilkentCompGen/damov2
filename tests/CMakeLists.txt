# Lightweight test harness — no external framework, just assert-based binaries
# registered with CTest.
add_executable(test_locality test_locality.cpp)
target_link_libraries(test_locality PRIVATE damov_core)
add_test(NAME locality COMMAND test_locality)

add_executable(test_classify test_classify.cpp)
target_link_libraries(test_classify PRIVATE damov_core)
add_test(NAME classify COMMAND test_classify)

add_executable(test_metrics test_metrics.cpp)
target_link_libraries(test_metrics PRIVATE damov_core)
add_test(NAME metrics COMMAND test_metrics)
