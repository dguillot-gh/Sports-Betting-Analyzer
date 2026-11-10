using System.IO;
using System.Text.RegularExpressions;

namespace SportsBettingAnalyzer.Tests;

/// <summary>
/// Guards the IPythonMLServiceClient contract: the interface must declare
/// exactly the same public async method surface as the partial implementation
/// files (name + parameter list). Return-type drift is additionally caught at
/// compile time, because PythonMLServiceClient implements the interface.
/// </summary>
public class PythonMLServiceClientInterfaceTests
{
    private static readonly string[] PartialFiles =
    {
        "PythonMLServiceClient.cs",
        "PythonMLServiceClient.Ncaab.cs",
        "PythonMLServiceClient.Nascar.cs",
        "PythonMLServiceClient.Nba.cs",
        "PythonMLServiceClient.Nfl.cs",
    };

    [Fact]
    public void Interface_File_Exists()
    {
        var dir = PythonMLServiceClientSplitTests.FindServicesDir();
        Assert.True(File.Exists(dir + "/IPythonMLServiceClient.cs"), "IPythonMLServiceClient.cs is missing from frontend/Services");
    }

    [Fact]
    public void Implementation_DeclaresInterfaceInCoreFile()
    {
        var dir = PythonMLServiceClientSplitTests.FindServicesDir();
        var core = File.ReadAllText(dir + "/PythonMLServiceClient.cs");
        Assert.Contains("public partial class PythonMLServiceClient : IPythonMLServiceClient", core);
    }

    [Fact]
    public void Interface_Signatures_MatchImplementation()
    {
        var dir = PythonMLServiceClientSplitTests.FindServicesDir();

        var rgx = new Regex(
            @"^\s*(?:public\s+)?(?:async\s+)?Task(?:<[^;]*>)?\s+([A-Za-z_]\w*)\s*\(([^)\n]*)\)",
            RegexOptions.Multiline);

        var interfaceSource = File.ReadAllText(dir + "/IPythonMLServiceClient.cs");
        var impl = new System.Text.StringBuilder();
        foreach (var file in PartialFiles)
            impl.AppendLine(File.ReadAllText(dir + "/" + file));

        var fromInterface = new HashSet<string>(rgx.Matches(interfaceSource)
            .Cast<Match>().Select(Method));
        var fromImpl = new HashSet<string>(rgx.Matches(impl.ToString())
            .Cast<Match>().Select(Method));

        Assert.True(fromInterface.Count > 20, $"regex matched only {fromInterface.Count} interface members; guard is broken");
        Assert.Equal(fromImpl, fromInterface);
    }

    [Theory]
    [InlineData("IsHealthyAsync")]
    [InlineData("TrainNcaabModelAsync")]
    [InlineData("CompareNbaModelsAsync")]
    [InlineData("PredictNflBatchAsync")]
    [InlineData("GetDeploymentHistoryAsync")]
    public void Interface_DeclaresCoreMethod(string member)
    {
        var dir = PythonMLServiceClientSplitTests.FindServicesDir();
        var source = File.ReadAllText(dir + "/IPythonMLServiceClient.cs");
        Assert.Contains(member + "(", source);
    }

    private static string Method(Match m) =>
        $"{m.Groups[1].Value}({m.Groups[2].Value.Replace(" ", "")})";

    // --- DI registration guard -------------------------------------------------

    [Fact]
    [Trait("Category", "Guard")]
    public void Program_Registers_The_Interface_Itself()
    {
        // Guards against a real production incident: AddTransient(sp => sp.GetRequiredService<TClient>())
        // infers the registered service type from the RETURN value (TClient), so it registers the
        // concrete class again and the interface silently fails to resolve at runtime
        // ("There is no registered service of type 'IPythonMLServiceClient'").
        var dir = PythonMLServiceClientSplitTests.FindServicesDir();
        var program = File.ReadAllText(dir + "/../Program.cs"); // frontend/Services/../Program.cs
        Assert.Contains("AddTransient<IPythonMLServiceClient>", program);
    }
}
