using System.Net.Http.Json;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Shared.Services;

public class VersionInfo
{
    public string Version { get; set; } = "";
    public string GitSha { get; set; } = "";
    public string GitBranch { get; set; } = "";
    public int CommitCount { get; set; }
    public string CommitMessage { get; set; } = "";
    public string BuildTime { get; set; } = "";
    public string Environment { get; set; } = "";
}

public interface IVersionService
{
    Task<VersionInfo> GetVersionInfoAsync();
    Task<string> GetVersionAsync();
}

public class VersionService : IVersionService
{
    private readonly HttpClient _http;
    private readonly IServerConfigService _serverConfig;

    public VersionService(HttpClient http, IServerConfigService serverConfig)
    {
        _http = http;
        _serverConfig = serverConfig;
    }

    public async Task<VersionInfo> GetVersionInfoAsync()
    {
        try
        {
            var baseUrl = _serverConfig.GetBaseUrl();
            var response = await _http.GetFromJsonAsync<VersionInfo>($"{baseUrl}/version");
            return response ?? new VersionInfo { Version = "Unknown" };
        }
        catch
        {
            return new VersionInfo 
            { 
                Version = "Error", 
                Environment = "Offline",
                GitBranch = "Unknown",
                GitSha = "Unknown"
            };
        }
    }

    public async Task<string> GetVersionAsync()
    {
        var versionInfo = await GetVersionInfoAsync();
        return versionInfo.Version;
    }
}
