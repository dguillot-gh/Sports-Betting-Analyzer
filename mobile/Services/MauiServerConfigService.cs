using Microsoft.Maui.Devices;
using Microsoft.Maui.Storage;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Mobile.Services;

public class MauiServerConfigService : IServerConfigService
{
    private const string ServerUrlKey = "BackendServerUrl";

    // 10.0.2.2 aliases the host loopback inside the Android emulator only;
    // real devices need the LAN IP of the machine running the backend
    // (port 8003 matches docker-compose(-.portainer).yml backend mapping).
    private static string FallbackBaseUrl =>
        IsEmulator() ? "http://10.0.2.2:8003" : "http://192.168.0.42:8003";

    // 10.0.2.2 aliases the host loopback inside the Android emulator only.
    // Emulator device models look like sdk_gphone64_arm64 / vbox86p; real
    // hardware uses manufacturer codenames (e.g. "shiba" for a Pixel 8).
    private static bool IsEmulator()
    {
        var model = (DeviceInfo.Model ?? "").ToLowerInvariant();
        return model.Contains("sdk_gphone") || model.Contains("sdk_gtablet") ||
               model.StartsWith("vbox86") || model.Contains("emulator");
    }

    public string GetBaseUrl()
    {
        var baseUrl = Preferences.Get(ServerUrlKey, FallbackBaseUrl);
        return ApiUrlHelper.NormalizeBaseUrl(baseUrl, FallbackBaseUrl);
    }

    public void SetBaseUrl(string url)
    {
        if (string.IsNullOrWhiteSpace(url)) return;

        Preferences.Set(ServerUrlKey, ApiUrlHelper.NormalizeBaseUrl(url, FallbackBaseUrl));
    }
}
