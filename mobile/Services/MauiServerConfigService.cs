using Microsoft.Maui.Storage;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Mobile.Services;

public class MauiServerConfigService : IServerConfigService
{
    private const string ServerUrlKey = "BackendServerUrl";

    public string GetBaseUrl()
    {
        // Default to the Android Emulator loopback IP (10.0.2.2) 
        // using port 8003 (which matches your docker-compose.yml mapping for the backend).
        var baseUrl = Preferences.Get(ServerUrlKey, "http://10.0.2.2:8003");
        return ApiUrlHelper.NormalizeBaseUrl(baseUrl, "http://10.0.2.2:8003");
    }

    public void SetBaseUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;

        Preferences.Set(ServerUrlKey, ApiUrlHelper.NormalizeBaseUrl(url, "http://10.0.2.2:8003"));
    }
}
