// Common entry point for the GoogleTest unit-test binary. Provided here so the
// suite links regardless of whether libgtest_main is available.
#include <gtest/gtest.h>

int main(int argc, char** argv)
{
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
