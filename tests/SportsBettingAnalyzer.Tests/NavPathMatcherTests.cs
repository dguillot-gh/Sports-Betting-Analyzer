using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Tests;

public class NavPathMatcherTests
{
    [Theory]
    [InlineData("/nfl", "/nfl", true)]
    [InlineData("/nfl", "/nfl/scores", true)]
    [InlineData("nfl", "nfl/scores", true)]
    [InlineData("NFL", "/nfl", true)]
    [InlineData("/nfl", "/nba", false)]
    [InlineData("/nfl", "/nflx", false)]
    [InlineData("/nfl", "/", false)]
    [InlineData("/nfl", "", false)]
    [InlineData("/nfl", null, false)]
    public void IsActive_MatchesExactOrChildRoute(string url, string? current, bool expected)
    {
        Assert.Equal(expected, NavPathMatcher.IsActive(url, current));
    }

    [Theory]
    [InlineData(null, false)]
    [InlineData("", false)]
    [InlineData("   ", false)]
    public void IsActive_NullOrBlankUrl_ReturnsFalse(string? url, bool expected)
    {
        Assert.Equal(expected, NavPathMatcher.IsActive(url, "/nfl"));
    }

    [Fact]
    public void IsActive_MenuToggleSentinel_ReturnsFalse()
    {
        Assert.False(NavPathMatcher.IsActive(NavPathMatcher.MenuToggle, "/menu-toggle"));
        Assert.False(NavPathMatcher.IsActive("menu_toggle", "/"));
    }

    [Theory]
    [InlineData(null, "/")]
    [InlineData("", "/")]
    [InlineData("/nfl", "/nfl")]
    [InlineData("nfl", "/nfl")]
    [InlineData("nfl/scores", "/nfl/scores")]
    [InlineData("/nfl/", "/nfl/")]
    [InlineData("  nba  ", "/nba")]
    public void ToAbsolutePath_NormalizesUrls(string? url, string expected)
    {
        Assert.Equal(expected, NavPathMatcher.ToAbsolutePath(url));
    }
}
