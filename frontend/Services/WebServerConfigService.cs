using Microsoft.Extensions.Configuration;
using SportsBettingAnalyzer.Shared.Services;

namespace SportsBettingAnalyzer.Services;

public class WebServerConfigService : IServerConfigService
{
    private string _baseUrl;

    public WebServerConfigService(IConfiguration config)
    {
        _baseUrl = ApiUrlHelper.NormalizeBaseUrl(config["PythonMLService:BaseUrl"], "http://localhost:8000");
    }

    public string GetBaseUrl() => _baseUrl;

    public void SetBaseUrl(string url)
    {
        _baseUrl = ApiUrlHelper.NormalizeBaseUrl(url, "http://localhost:8000");
    }
}
