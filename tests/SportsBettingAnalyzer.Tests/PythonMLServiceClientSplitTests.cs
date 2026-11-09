using System.IO;

namespace SportsBettingAnalyzer.Tests;

/// <summary>
/// Guards the split of PythonMLServiceClient into partial files: the public
/// method surface after the split must exactly match what the pre-split file
/// declared (same methods, same signatures, no duplicates).
/// </summary>
public class PythonMLServiceClientSplitTests
{
    private static readonly string[] PartialFiles =
    {
        "PythonMLServiceClient.cs",
        "PythonMLServiceClient.Dtos.cs",
        "PythonMLServiceClient.Ncaab.cs",
        "PythonMLServiceClient.Nascar.cs",
        "PythonMLServiceClient.Nba.cs",
        "PythonMLServiceClient.Nfl.cs",
    };

    internal static string FindServicesDir()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = new DirectoryInfo(dir.FullName + "/frontend/Services");
            if (candidate.Exists && File.Exists(candidate.FullName + "/PythonMLServiceClient.cs"))
                return candidate.FullName;
            dir = dir.Parent;
        }
        throw new DirectoryNotFoundException("Could not locate frontend/Services walking up from " + AppContext.BaseDirectory);
    }

    private static string AllClientSource()
    {
        var dir = FindServicesDir();
        var sb = new System.Text.StringBuilder();
        foreach (var file in PartialFiles)
            sb.AppendLine(File.ReadAllText(dir + "/" + file));
        return sb.ToString();
    }

    [Fact]
    public void All_PartialFiles_Exist()
    {
        var dir = FindServicesDir();
        foreach (var file in PartialFiles)
        {
            Assert.True(File.Exists(dir + "/" + file), $"missing partial file: {file}");
        }
    }

    [Fact]
    public void CoreFile_DeclaresPartialClass()
    {
        var dir = FindServicesDir();
        var core = File.ReadAllText(dir + "/PythonMLServiceClient.cs");
        Assert.Contains("public partial class PythonMLServiceClient", core);
    }

    [Fact]
    public void PublicMethodSignatures_MatchPreSplitCommit()
    {
        var rgx = new System.Text.RegularExpressions.Regex(
            @"^\s*public\s+(?:async\s+)?([\w?<>[\], ]+?)\s+([A-Za-z_]\w*)\s*\(([^)\n]*)\)",
            System.Text.RegularExpressions.RegexOptions.Multiline);

        var split = new HashSet<string>(rgx.Matches(AllClientSource())
            .Cast<System.Text.RegularExpressions.Match>()
            .Select(m => Signature(m)));

        var process = System.Diagnostics.Process.Start(
            new System.Diagnostics.ProcessStartInfo("git", "show dcbedf2:frontend/Services/PythonMLServiceClient.cs")
            { RedirectStandardOutput = true, UseShellExecute = false, WorkingDirectory = FindServicesDir() });
        string original = process?.StandardOutput.ReadToEnd() ?? "";
        process?.WaitForExit();
        Assert.True(process is not null && process.ExitCode == 0, "git show failed");

        var expected = new HashSet<string>(rgx.Matches(original)
            .Cast<System.Text.RegularExpressions.Match>()
            .Select(m => Signature(m)));

        Assert.True(expected.Count > 20, $"signature regex matched only {expected.Count} members; guard is broken");
        Assert.Equal(expected, split);
    }

    private static string Signature(System.Text.RegularExpressions.Match m) =>
        $"{m.Groups[1].Value.Trim()} {m.Groups[2].Value}({m.Groups[3].Value.Replace(" ", "")})";

    [Theory]
    [InlineData("TrainNcaabModelAsync")]
    [InlineData("CompareNbaModelsAsync")]
    [InlineData("PredictNflBatchAsync")]
    [InlineData("SimulateRaceAsync")]
    [InlineData("CompareNcaabModelsAsync")]
    [InlineData("IsHealthyAsync")]
    [InlineData("CreateReleaseAsync")]
    public void PublicMethods_SurvivedTheSplit(string member)
    {
        Assert.Contains(member + "(", AllClientSource());
    }
}
