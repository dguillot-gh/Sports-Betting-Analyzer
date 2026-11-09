using System.IO;

namespace SportsBettingAnalyzer.Tests;

/// <summary>
/// Regression guards for the mobile app theme: the app must stay on the dark
/// token palette and must not reintroduce light-only leftovers that previously
/// leaked from the Blazor template CSS.
/// </summary>
public class MobileThemeCssTests
{
    private static string FindRepoFile(string relative)
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, relative.Replace('/', Path.DirectorySeparatorChar));
            if (File.Exists(candidate)) return candidate;
            dir = dir.Parent;
        }
        throw new FileNotFoundException($"Could not locate '{relative}' walking up from {AppContext.BaseDirectory}");
    }

    private static string AppCss => File.ReadAllText(FindRepoFile("mobile/wwwroot/css/app.css"));

    [Fact]
    public void Theme_IsDarkColorScheme()
    {
        Assert.Contains("color-scheme: dark", AppCss);
    }

    [Fact]
    public void Theme_DefinesDarkTokens()
    {
        foreach (var token in new[] { "--bg:", "--surface:", "--text-primary:", "--border:" })
        {
            Assert.Contains(token, AppCss);
        }
    }

    [Theory]
    [InlineData("lightyellow")]
    [InlineData("color-scheme: light only")]
    [InlineData("background: white")]
    public void Theme_HasNoLightOnlyLeftovers(string leftover)
    {
        Assert.DoesNotContain(leftover, AppCss, System.StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void DeadTemplateStylesheet_IsRemoved()
    {
        // The unlinked mobile/wwwroot/app.css (template default, light-only) was a theme landmine.
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !Directory.Exists(Path.Combine(dir.FullName, "mobile", "wwwroot")))
        {
            dir = dir.Parent;
        }
        Assert.NotNull(dir);
        Assert.False(File.Exists(Path.Combine(dir!.FullName, "mobile", "wwwroot", "app.css")),
            "mobile/wwwroot/app.css should have been removed in favor of css/app.css");
    }

    [Fact]
    public void IndexHtml_LinksTheDarkStylesheet()
    {
        var html = File.ReadAllText(FindRepoFile("mobile/wwwroot/index.html"));
        Assert.Contains("css/app.css", html);
    }
}
