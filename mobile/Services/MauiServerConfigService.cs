using Microsoft.Maui.Storage;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Mobile.Services;

public class MauiServerConfigService : IServerConfigService
{
    private const string ServerUrlKey = "BackendServerUrl";

    public string GetBaseUrl()
    {
        // Default to the Android Emulator loopback IP (10.0.2.2) 
        // to reach the host PC if running locally. Users can change this in the Settings UI.
        return Preferences.Get(ServerUrlKey, "http://10.0.2.2:8000");
    }

    public void SetBaseUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;
        
        // Formatting safety check
        if (!url.EndsWith("/")) url += "/";
        Preferences.Set(ServerUrlKey, url);
    }
}
