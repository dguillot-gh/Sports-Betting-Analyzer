using System.Net.Http.Json;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class OddsService
    {
        private readonly HttpClient _httpClient;
        private readonly string _apiKey;
        private readonly string _baseUrl;
        private readonly ILogger<OddsService> _logger;

        public OddsService(HttpClient httpClient, IConfiguration configuration, ILogger<OddsService> logger)
        {
            _httpClient = httpClient;
            _apiKey = configuration["OddsApi:ApiKey"] ?? throw new ArgumentNullException("OddsApi:ApiKey not found in configuration");
            _baseUrl = configuration["OddsApi:BaseUrl"] ?? "https://api.the-odds-api.com/v4";
            _logger = logger;
        }

        public QuotaInfo LastQuotaUsage { get; private set; } = new();

        private void UpdateQuotaInfo(HttpResponseMessage response)
        {
            if (response.Headers.TryGetValues("x-requests-remaining", out var remaining) && int.TryParse(remaining.FirstOrDefault(), out int r))
                LastQuotaUsage.RequestsRemaining = r;

            if (response.Headers.TryGetValues("x-requests-used", out var used) && int.TryParse(used.FirstOrDefault(), out int u))
                LastQuotaUsage.RequestsUsed = u;

            if (response.Headers.TryGetValues("x-requests-last", out var last) && int.TryParse(last.FirstOrDefault(), out int l))
                LastQuotaUsage.RequestsLast = l;
        }

        public async Task<List<SportInfo>> GetSportsAsync()
        {
            try
            {
                var url = $"{_baseUrl}/sports?apiKey={_apiKey}";
                var response = await _httpClient.GetAsync(url);
                UpdateQuotaInfo(response);
                
                return await response.Content.ReadFromJsonAsync<List<SportInfo>>() ?? new List<SportInfo>();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching sports from Odds API");
                return new List<SportInfo>();
            }
        }

        public async Task<List<OddsEvent>> GetOddsAsync(string sportKey, string region = "us", string markets = "h2h,spreads,totals", string bookmakers = "draftkings,fanduel")
        {
            try
            {
                var url = $"{_baseUrl}/sports/{sportKey}/odds?apiKey={_apiKey}&regions={region}&markets={markets}&bookmakers={bookmakers}&oddsFormat=american";
                _logger.LogInformation("Fetching odds from: {Url}", url.Replace(_apiKey, "***"));
                
                var response = await _httpClient.GetAsync(url);
                UpdateQuotaInfo(response);
                _logger.LogInformation("Response status: {StatusCode}", response.StatusCode);
                
                if (!response.IsSuccessStatusCode)
                {
                    var errorContent = await response.Content.ReadAsStringAsync();
                    _logger.LogError("API returned error: {StatusCode} - {Content}", response.StatusCode, errorContent);
                    return new List<OddsEvent>();
                }
                
                var events = await response.Content.ReadFromJsonAsync<List<OddsEvent>>() ?? new List<OddsEvent>();
                _logger.LogInformation("Successfully fetched {Count} events for {SportKey}", events.Count, sportKey);
                
                return events;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching odds for {SportKey}", sportKey);
                return new List<OddsEvent>();
            }
        }
        public async Task<OddsEvent?> GetEventOddsAsync(string sportKey, string eventId, string region = "us", string markets = "player_pass_tds,player_pass_yds,player_rush_yds,player_rush_att,player_reception_yds,player_receptions", string bookmakers = "draftkings,fanduel")
        {
            try
            {
                var url = $"{_baseUrl}/sports/{sportKey}/events/{eventId}/odds?apiKey={_apiKey}&regions={region}&markets={markets}&bookmakers={bookmakers}&oddsFormat=american";
                _logger.LogInformation("Fetching event odds from: {Url}", url.Replace(_apiKey, "***"));
                
                var response = await _httpClient.GetAsync(url);
                UpdateQuotaInfo(response);
                
                if (!response.IsSuccessStatusCode)
                {
                     var errorContent = await response.Content.ReadAsStringAsync();
                    _logger.LogError("API returned error: {StatusCode} - {Content}", response.StatusCode, errorContent);
                    return null;
                }

                return await response.Content.ReadFromJsonAsync<OddsEvent>();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching event odds for {EventId}", eventId);
                return null;
            }
        }
    }
}
