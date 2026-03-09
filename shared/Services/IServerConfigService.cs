namespace SportsBettingAnalyzer.Shared.Services;

public interface IServerConfigService
{
    string GetBaseUrl();
    void SetBaseUrl(string url);
}
