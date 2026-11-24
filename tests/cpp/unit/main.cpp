// Entry point for the OpenUxAS C++ unit tests (GoogleTest).
//
// New test files placed in tests/cpp/unit/ (as test_*.cpp) are picked up
// automatically by the `make test` target.

#include <gtest/gtest.h>

int main(int argc, char** argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
