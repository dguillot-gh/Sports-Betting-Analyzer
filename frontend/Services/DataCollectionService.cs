using System.Net.Http.Json;
using System.Text.Json;
using System.Linq;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class DataCollectionService
    {
        private readonly HttpClient _http;
        private readonly ILogger<DataCollectionService> _logger;
        private readonly string _apiBaseUrl;

        public DataCollectionService(HttpClient http, IConfiguration configuration, ILogger<DataCollectionService> logger)
        {
            _http = http;
            _logger = logger;
            _apiBaseUrl = configuration["PythonApiUrl"] ?? "http://backend:8000";
        }

        public async Task SaveBetAnalysisAsync(BetAnalysis analysis)
        {
            try
            {
                var req = new
                {
                    sport = analysis.BetSlip.Sport?.ToLower() ?? "nba",
                    bet_type = analysis.BetSlip.BetType?.ToLower() ?? "single",
                    sportsbook = "fanduel", // Default
                    stake = (double)analysis.BetSlip.WagerAmount,
                    odds = (int)analysis.BetSlip.Odds,
                    description = $"AI Analysis: {analysis.BetSlip.BetType}",
                    source = "ai_analyzer",
                    expected_value = (double)analysis.ExpectedValue,
                    recommendation = analysis.Recommendation,
                    confidence_score = (double)analysis.ConfidenceScore,
                    team1 = analysis.BetSlip.Team1,
                    team2 = analysis.BetSlip.Team2,
                    player_name = analysis.BetSlip.PlayerName,
                    game_date = analysis.BetSlip.GameDate?.ToString("yyyy-MM-ddTHH:mm:ssZ") ?? DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
                };

                var response = await _http.PostAsJsonAsync($"{_apiBaseUrl}/bets", req);
                response.EnsureSuccessStatusCode();

                _logger.LogInformation("Saved bet analysis to backend API");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error saving bet analysis to API");
                throw;
            }
        }

        public async Task UpdateBetResultAsync(int betId, bool won, decimal? payout = null)
        {
            try
            {
                var outcome = won ? "win" : "loss";
                var req = new { outcome = outcome };
                
                var response = await _http.PatchAsJsonAsync($"{_apiBaseUrl}/bets/{betId}/outcome", req);
                response.EnsureSuccessStatusCode();

                _logger.LogInformation("Updated bet result for ID {Id}: {Outcome}", betId, outcome);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error updating bet result via API");
                throw;
            }
        }

        public async Task<List<HistoricalBet>> GetHistoricalBetsAsync(int? limit = null)
        {
            try
            {
                var url = $"{_apiBaseUrl}/bets?limit={limit ?? 50}";
                var response = await _http.GetFromJsonAsync<BetListResponse>(url);
                
                if (response?.Bets == null) return new List<HistoricalBet>();

                return response.Bets.Select(b => new HistoricalBet
                {
                    Id = b.Id,
                    Team1 = b.Team1 ?? b.GameName?.Split(" @ ").LastOrDefault() ?? b.Description,
                    Team2 = b.Team2 ?? b.GameName?.Split(" @ ").FirstOrDefault(),
                    PlayerName = b.PlayerName,
                    Odds = (decimal)(b.Odds ?? 0),
                    BetType = b.BetType,
                    WagerAmount = (decimal)b.Stake,
                    Sport = b.Sport,
                    GameDate = DateTime.TryParse(b.GameDate, out var gd) ? gd : (DateTime.TryParse(b.CreatedAt, out var cd) ? cd : DateTime.UtcNow),
                    ExpectedValue = (decimal)(b.ExpectedValue ?? 0.0),
                    Recommendation = b.Recommendation ?? "Unknown",
                    ConfidenceScore = (decimal)(b.ConfidenceScore ?? 0.0),
                    AnalyzedAt = DateTime.TryParse(b.CreatedAt, out var cat) ? cat : DateTime.UtcNow,
                    Won = b.Outcome == "win" ? true : (b.Outcome == "loss" ? false : (bool?)null),
                    Payout = b.CashoutAmount.HasValue ? (decimal)b.CashoutAmount.Value : (decimal?)null
                }).ToList();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error retrieving historical bets from API");
                return new List<HistoricalBet>();
            }
        }

        public async Task<List<HistoricalBet>> GetBetsForTrainingAsync()
        {
            // Fetch a relatively large batch and filter for those with results
            var allBets = await GetHistoricalBetsAsync(200);
            return allBets.Where(b => b.Won.HasValue).ToList();
        }

        public async Task<Dictionary<string, object>> GetAnalyticsAsync()
        {
            try
            {
                var response = await _http.GetFromJsonAsync<JsonElement>($"{_apiBaseUrl}/bets/stats/summary");
                
                return new Dictionary<string, object>
                {
                    { "TotalBets", response.GetProperty("total_bets").GetInt32() },
                    { "BetsWithResults", response.GetProperty("wins").GetInt32() + response.GetProperty("losses").GetInt32() },
                    { "WonBets", response.GetProperty("wins").GetInt32() },
                    { "WinRate", response.GetProperty("win_percentage").GetDouble() / 100.0 },
                    { "TotalWagered", (decimal)response.GetProperty("total_staked").GetDouble() },
                    { "TotalPayout", (decimal)(response.GetProperty("total_staked").GetDouble() + response.GetProperty("net_profit").GetDouble()) },
                    { "NetProfit", (decimal)response.GetProperty("net_profit").GetDouble() },
                    { "GoodBetCount", 0 } // Potential future field
                };
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error getting analytics from API");
                return new Dictionary<string, object>();
            }
        }

        private class BetListResponse
        {
            public List<ApiBet> Bets { get; set; } = new();
        }

        private class ApiBet
        {
            public int Id { get; set; }
            public string CreatedAt { get; set; } = "";
            public string Sport { get; set; } = "";
            public string BetType { get; set; } = "";
            public string Outcome { get; set; } = "pending";
            public double Stake { get; set; }
            public double? Odds { get; set; }
            public double? ExpectedValue { get; set; }
            public string? Recommendation { get; set; }
            public double? ConfidenceScore { get; set; }
            public string? Team1 { get; set; }
            public string? Team2 { get; set; }
            public string? PlayerName { get; set; }
            public string? GameDate { get; set; }
            public string? GameName { get; set; }
            public string? Description { get; set; }
            public double? CashoutAmount { get; set; }
        }
    }
}

