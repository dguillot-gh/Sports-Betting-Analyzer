using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.Extensions.Logging;
using Microsoft.AspNetCore.Components.Forms;
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

        public async Task DeleteBetAsync(int betId)
        {
            try
            {
                var response = await _http.DeleteAsync($"{_apiBaseUrl}/bets/{betId}");
                response.EnsureSuccessStatusCode();
                _logger.LogInformation("Deleted bet ID {Id}", betId);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error deleting bet via API");
                throw;
            }
        }

        public async Task ClearAllBetsAsync()
        {
            try
            {
                var response = await _http.DeleteAsync($"{_apiBaseUrl}/bets/all");
                response.EnsureSuccessStatusCode();
                _logger.LogInformation("Cleared all bet history");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error clearing all bets via API");
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

        public async Task<ImportPreviewResponse?> PreviewImportAsync(IBrowserFile file)
        {
            try
            {
                using var content = new MultipartFormDataContent();
                var fileContent = new StreamContent(file.OpenReadStream(maxAllowedSize: 10 * 1024 * 1024)); // 10MB max
                content.Add(fileContent, "file", file.Name);

                var response = await _http.PostAsync($"{_apiBaseUrl}/bets/preview-import", content);
                response.EnsureSuccessStatusCode();

                return await response.Content.ReadFromJsonAsync<ImportPreviewResponse>();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error previewing import");
                throw;
            }
        }

        public async Task ConfirmImportAsync(List<ImportBetPreview> bets)
        {
            try
            {
                var response = await _http.PostAsJsonAsync($"{_apiBaseUrl}/bets/confirm-import", bets);
                response.EnsureSuccessStatusCode();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error confirming import");
                throw;
            }
        }

        public async Task<MultiSportAnalysisResponse?> GetMultiSportAnalysisAsync(string sportsbook = "fanduel")
        {
            try
            {
                return await _http.GetFromJsonAsync<MultiSportAnalysisResponse>($"{_apiBaseUrl}/odds/all-sports/analyze?sportsbook={sportsbook}");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching multi-sport analysis");
                return null;
            }
        }

        public async Task<JsonElement?> GetAIAnalysisAsync(string sport, string home, string away, string homeStats = "", string awayStats = "", bool shortPrompt = false)
        {
            try
            {
                var url = $"{_apiBaseUrl}/ai/analyze?sport={sport}&home_team={Uri.EscapeDataString(home)}&away_team={Uri.EscapeDataString(away)}";
                if (!string.IsNullOrEmpty(homeStats)) url += $"&home_stats={Uri.EscapeDataString(homeStats)}";
                if (!string.IsNullOrEmpty(awayStats)) url += $"&away_stats={Uri.EscapeDataString(awayStats)}";
                if (shortPrompt) url += "&short_prompt=true";
                
                var response = await _http.PostAsync(url, null);
                response.EnsureSuccessStatusCode();
                return await response.Content.ReadFromJsonAsync<JsonElement>();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching AI analysis for {Away} @ {Home}", away, home);
                return null;
            }
        }

        public async Task<JsonElement?> GetNascarPredictionsAsync(int raceId)
        {
            try
            {
                return await _http.GetFromJsonAsync<JsonElement>($"{_apiBaseUrl}/nascar/predictions/{raceId}");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching NASCAR predictions for race {RaceId}", raceId);
                return null;
            }
        }

        public async Task<JsonElement?> GetNascarStatusAsync()
        {
            try
            {
                return await _http.GetFromJsonAsync<JsonElement>($"{_apiBaseUrl}/nascar/status");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching NASCAR status");
                return null;
            }
        }

        public async Task<JsonElement?> GetNascarOddsAsync()
        {
            try
            {
                return await _http.GetFromJsonAsync<JsonElement>($"{_apiBaseUrl}/nascar/odds");
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching NASCAR odds");
                return null;
            }
        }

        public async Task<JsonElement?> UploadNascarOddsAsync(IBrowserFile file)
        {
            try
            {
                using var content = new MultipartFormDataContent();
                var fileContent = new StreamContent(file.OpenReadStream(maxAllowedSize: 10 * 1024 * 1024)); // 10MB max
                fileContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(file.ContentType);
                content.Add(fileContent, "file", file.Name);

                var response = await _http.PostAsync($"{_apiBaseUrl}/nascar/upload-odds", content);
                if (response.IsSuccessStatusCode)
                {
                    return await response.Content.ReadFromJsonAsync<JsonElement>();
                }
                else
                {
                    var errorContent = await response.Content.ReadAsStringAsync();
                    throw new Exception($"Server Error {response.StatusCode}: {errorContent}");
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error uploading odds image");
                throw; // Rethrow to let UI handle it
            }
        }

        public async Task<string> GetNascarRaceAnalysisAsync(List<DriverPrediction> drivers, string trackName)
        {
            try
            {
                var payload = new 
                { 
                    race_details = new { track = trackName, series = "NASCAR Cup Series" },
                    drivers = drivers.Select(d => new { 
                        driver_name = d.DriverName, 
                        win_probability = d.WinProbability, 
                        projected_finish = d.ProjectedFinish,
                        market_odds = d.MarketOdds,
                        confidence = d.Confidence
                    }) 
                };
                
                var response = await _http.PostAsJsonAsync($"{_apiBaseUrl}/nascar/analyze-race", payload);
                if (response.IsSuccessStatusCode)
                {
                    var result = await response.Content.ReadFromJsonAsync<JsonElement>();
                    return result.GetProperty("analysis").GetString() ?? "No analysis returned.";
                }
                return $"Error: {await response.Content.ReadAsStringAsync()}";
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error getting race analysis");
                return $"Error: {ex.Message}";
            }
        }

        public async Task<bool> SubmitManualOddsAsync(List<DriverPrediction> drivers)
        {
            try
            {
                var payload = new { drivers = drivers.Select(d => new { driver_name = d.DriverName, market_odds = d.MarketOdds }) };
                var response = await _http.PostAsJsonAsync($"{_apiBaseUrl}/nascar/manual-odds", payload);
                if (response.IsSuccessStatusCode)
                {
                    return true;
                }
                var error = await response.Content.ReadAsStringAsync();
                _logger.LogError($"Failed to submit manual odds: {error}");
                return false;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error submitting manual odds");
                return false;
            }
        }

        public class MultiSportAnalysisResponse
        {
            [System.Text.Json.Serialization.JsonPropertyName("timestamp")]
            public string Timestamp { get; set; } = "";
            
            [System.Text.Json.Serialization.JsonPropertyName("total_games")]
            public int TotalGames { get; set; }
            
            [System.Text.Json.Serialization.JsonPropertyName("total_value_bets")]
            public int TotalValueBets { get; set; }
            
            [System.Text.Json.Serialization.JsonPropertyName("all_games")]
            public List<JsonElement> AllGames { get; set; } = new();
        }

        public class ImportPreviewResponse
        {
            [System.Text.Json.Serialization.JsonPropertyName("bets")]
            public List<ImportBetPreview> Bets { get; set; } = new();

            [System.Text.Json.Serialization.JsonPropertyName("total_count")]
            public int TotalCount { get; set; }
        }

        public class ImportBetPreview
        {
            [System.Text.Json.Serialization.JsonPropertyName("date")]
            public string? Date { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("sport")]
            public string? Sport { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("description")]
            public string? Description { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("stake")]
            public double Stake { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("odds")]
            public int Odds { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("outcome")]
            public string? Outcome { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("profit")]
            public double Profit { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("sportsbook")]
            public string? Sportsbook { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("bet_type")]
            public string? BetType { get; set; }

            [System.Text.Json.Serialization.JsonPropertyName("legs")]
            public List<ImportBetPreview>? Legs { get; set; }
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

