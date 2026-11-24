// Trivial suite that does not require liblmcp. It validates that the
// GoogleTest wiring (make test) and the C++17 toolchain work.
#include <gtest/gtest.h>

#include <optional>
#include <string>
#include <string_view>

TEST(Smoke, CxxStandardIsAtLeast17)
{
    EXPECT_GE(__cplusplus, 201703L);
}

TEST(Smoke, Cxx17FeaturesCompile)
{
    std::optional<std::string> value;
    EXPECT_FALSE(value.has_value());
    value = "uxas";
    std::string_view view{*value};
    EXPECT_EQ(view, "uxas");
    if constexpr (sizeof(int) >= 2)
    {
        SUCCEED();
    }
}
