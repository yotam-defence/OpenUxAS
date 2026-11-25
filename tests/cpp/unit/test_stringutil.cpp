// Unit tests for uxas::common::StringUtil (header-only, no services needed).

#include "UxAS_StringUtil.h"

#include <gtest/gtest.h>

#include <string>
#include <vector>

using uxas::common::StringUtil;

TEST(StringUtil, SplitOnDelimiter)
{
    const std::vector<std::string> tokens = StringUtil::split("a,b,c", ',');
    ASSERT_EQ(tokens.size(), 3u);
    EXPECT_EQ(tokens[0], "a");
    EXPECT_EQ(tokens[1], "b");
    EXPECT_EQ(tokens[2], "c");
}

TEST(StringUtil, SplitNoDelimiterReturnsWholeString)
{
    const std::vector<std::string> tokens = StringUtil::split("abc", ',');
    ASSERT_EQ(tokens.size(), 1u);
    EXPECT_EQ(tokens[0], "abc");
}

TEST(StringUtil, SplitKeepsTrailingEmptyToken)
{
    const std::vector<std::string> tokens = StringUtil::split("a,b,", ',');
    ASSERT_EQ(tokens.size(), 3u);
    EXPECT_EQ(tokens[2], "");
}

TEST(StringUtil, ReplaceAllReplacesEveryOccurrence)
{
    std::string s = "foo bar foo";
    StringUtil::ReplaceAll(s, "foo", "baz");
    EXPECT_EQ(s, "baz bar baz");
}

TEST(StringUtil, ReplaceAllNoMatchLeavesStringUnchanged)
{
    std::string s = "hello";
    StringUtil::ReplaceAll(s, "xyz", "q");
    EXPECT_EQ(s, "hello");
}
