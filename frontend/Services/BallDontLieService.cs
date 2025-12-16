using System.Net.Http.Json;
using Microsoft.Extensions.Caching.Memory;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class BallDontLieService
    {
        private readonly HttpClient _httpClient;
        private readonly ILogger<BallDontLieService> _logger;
        private readonly IMemoryCache _cache;
        private readonly string _apiKey = "f87fec52-3532-47de-9675-24ec94fbe1dc"; // In prod, move to config
        
        private const string TEAMS_CACHE_KEY = "BDL_TEAMS";

        public QuotaInfo LastQuotaUsage { get; private set; } = new();

        public BallDontLieService(HttpClient httpClient, ILogger<BallDontLieService> logger, IMemoryCache cache)
        {
            _httpClient = httpClient;
            _logger = logger;
            _cache = cache;

            // BaseAddress set here is default (NBA), but we will override with absolute URIs for NFL
            _httpClient.BaseAddress = new Uri("https://api.balldontlie.io/v1/"); 
            _httpClient.DefaultRequestHeaders.Add("Authorization", _apiKey);
        }

        private string GetBaseUrl(string sport)
        {
            if (sport?.Contains("americanfootball", StringComparison.OrdinalIgnoreCase) == true || 
                sport?.Contains("nfl", StringComparison.OrdinalIgnoreCase) == true)
            {
                // Correct URL confirming with API: api.balldontlie.io/nfl/v1/
                return "https://api.balldontlie.io/nfl/v1/";
            }
            return "https://api.balldontlie.io/v1/";
        }

        public async Task<int?> GetTeamIdAsync(string teamName, string sport = "basketball_nba")
        {
            var teams = await GetTeamsAsync(sport);
            
            // Try exact match on 'Name' (e.g. Lakers or Cowboys)
            var match = teams.FirstOrDefault(t => t.Name.Equals(teamName, StringComparison.OrdinalIgnoreCase));
            if (match != null) return match.Id;
            
            // Try match on FullName (e.g. Los Angeles Lakers)
            match = teams.FirstOrDefault(t => t.FullName.Equals(teamName, StringComparison.OrdinalIgnoreCase));
            if (match != null) return match.Id;

            // Try partial match
            match = teams.FirstOrDefault(t => t.FullName.Contains(teamName, StringComparison.OrdinalIgnoreCase));
            return match?.Id;
        }

        public async Task<List<BallDontLieTeam>> GetTeamsAsync(string sport = "basketball_nba")
        {
            string baseUrl = GetBaseUrl(sport);
            // Cache key includes sport
            string cacheKey = $"{TEAMS_CACHE_KEY}_{sport}";

            if (_cache.TryGetValue(cacheKey, out List<BallDontLieTeam>? cachedTeams) && cachedTeams != null)
            {
                return cachedTeams;
            }

            try
            {
                var response = await _httpClient.GetAsync($"{baseUrl}teams");
                UpdateQuotaInfo(response);

                if (response.IsSuccessStatusCode)
                {
                    var result = await response.Content.ReadFromJsonAsync<BallDontLieResponse<List<BallDontLieTeam>>>();
                    if (result?.Data != null)
                    {
                        var teams = result.Data;
                        // Cache for 24 hours
                        _cache.Set(cacheKey, teams, TimeSpan.FromHours(24));
                        return teams;
                    }
                }
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching teams from BallDontLie ({Sport})", sport);
            }

            return new List<BallDontLieTeam>();
        }

        public async Task<TeamSeasonStats?> GetTeamStatsAsync(int teamId, string sport = "basketball_nba", int season = 2024)
        {
            string baseUrl = GetBaseUrl(sport);
            string cacheKey = $"BDL_STATS_{sport}_{teamId}_{season}";
            
            if (_cache.TryGetValue(cacheKey, out TeamSeasonStats? cachedStats) && cachedStats != null)
            {
                return cachedStats;
            }

            try
            {
                // Fetch games for the team in the season
                // Limit to 100 to calculate reasonably recent averages. API paginates 25 by default, max 100.
                var url = $"{baseUrl}games?seasons[]={season}&team_ids[]={teamId}&per_page=100";
                
                var response = await _httpClient.GetAsync(url);
                UpdateQuotaInfo(response);
                
                if (response.StatusCode == System.Net.HttpStatusCode.TooManyRequests)
                {
                    throw new HttpRequestException("Rate limit exceeded. Please wait a moment before trying again.", null, System.Net.HttpStatusCode.TooManyRequests);
                }

                if (!response.IsSuccessStatusCode) return null;

                var result = await response.Content.ReadFromJsonAsync<BallDontLieResponse<List<BallDontLieGame>>>();
                var games = result?.Data ?? new List<BallDontLieGame>();

                // Filter for completed games
                var completedGames = games
                    .Where(g => g.Status == "Final")
                    .OrderByDescending(g => g.Date) // Newest first
                    .ToList();

                if (!completedGames.Any()) return null;

                var stats = new TeamSeasonStats
                {
                    TeamId = teamId,
                    GamesPlayed = completedGames.Count,
                    TeamName = completedGames.First().HomeTeam.Id == teamId ? completedGames.First().HomeTeam.Name : completedGames.First().VisitorTeam.Name,
                    LastGameId = completedGames.First().Id
                };

                double totalPoints = 0;
                double totalPointsAllowed = 0;
                var form = new List<string>();
                double recentPoints = 0;
                int recentCount = 0;

                int i = 0;
                foreach (var game in completedGames)
                {
                    bool isHome = game.HomeTeam.Id == teamId;
                    int myScore = isHome ? game.HomeTeamScore : game.VisitorTeamScore;
                    int oppScore = isHome ? game.VisitorTeamScore : game.HomeTeamScore;

                    totalPoints += myScore;
                    totalPointsAllowed += oppScore;

                    // Last 5 games calculations
                    if (i < 5)
                    {
                        form.Add(myScore > oppScore ? "W" : "L");
                        recentPoints += myScore;
                        recentCount++;
                    }
                    i++;
                }

                stats.AveragePoints = totalPoints / completedGames.Count;
                stats.AveragePointsAllowed = totalPointsAllowed / completedGames.Count;
                stats.RecentForm = form; // Already in newest-first order
                stats.RecentPoints = recentCount > 0 ? recentPoints / recentCount : 0;

                // Cache for 30 minutes
                _cache.Set(cacheKey, stats, TimeSpan.FromMinutes(30));

                return stats;
            }
            catch (HttpRequestException)
            {
                throw; // Rethrow to let UI handle it
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching stats for team {TeamId}", teamId);
                return null;
            }
        }

        public async Task<List<BallDontLieGame>> GetHeadToHeadAsync(int teamId1, int teamId2, string sport = "basketball_nba")
        {
            string baseUrl = GetBaseUrl(sport);
            try
            {
                // Fetch recent games involving both teams
                // We request games for teamId1 and check opponent
                var url = $"{baseUrl}games?team_ids[]={teamId1}&per_page=100"; 
                // Note: BallDontLie free tier doesn't support complex filtering well, 
                // so we fetch team1's games and filter for team2 client-side.
                // Or verify if multiple team_ids[] implies OR or AND. Usually OR.
                // Let's filter client side from the last ~50 games of team1.
                
                var response = await _httpClient.GetAsync(url);
                UpdateQuotaInfo(response);

                if (response.StatusCode == System.Net.HttpStatusCode.TooManyRequests)
                {
                     throw new HttpRequestException("Rate limit exceeded. Please wait a moment before trying again.", null, System.Net.HttpStatusCode.TooManyRequests);
                }

                if (!response.IsSuccessStatusCode) return new List<BallDontLieGame>();

                var result = await response.Content.ReadFromJsonAsync<BallDontLieResponse<List<BallDontLieGame>>>();
                var games = result?.Data ?? new List<BallDontLieGame>();

                return games
                    .Where(g => (g.HomeTeam.Id == teamId1 && g.VisitorTeam.Id == teamId2) || 
                               (g.HomeTeam.Id == teamId2 && g.VisitorTeam.Id == teamId1))
                    .Where(g => g.Status == "Final")
                    .OrderByDescending(g => g.Date)
                    .Take(5)
                    .ToList();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching H2H");
                return new List<BallDontLieGame>();
            }
        }

        public async Task<List<BallDontLiePlayerStat>> GetGameStatsAsync(int gameId, string sport = "basketball_nba")
        {
             string baseUrl = GetBaseUrl(sport);
             try
            {
                var url = $"{baseUrl}stats?game_ids[]={gameId}&per_page=100";
                var response = await _httpClient.GetAsync(url);
                UpdateQuotaInfo(response);

                if (response.StatusCode == System.Net.HttpStatusCode.TooManyRequests)
                {
                    throw new HttpRequestException("Rate limit exceeded.", null, System.Net.HttpStatusCode.TooManyRequests);
                }

                if (!response.IsSuccessStatusCode) return new List<BallDontLiePlayerStat>();

                var result = await response.Content.ReadFromJsonAsync<BallDontLieResponse<List<BallDontLiePlayerStat>>>();
                return result?.Data ?? new List<BallDontLiePlayerStat>();
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error fetching game stats for {GameId}", gameId);
                return new List<BallDontLiePlayerStat>();
            }
        }

        private void UpdateQuotaInfo(HttpResponseMessage response)
        {
            // BallDontLie Headers: x-ratelimit-remaining, x-ratelimit-limit
            if (response.Headers.TryGetValues("x-ratelimit-remaining", out var remaining) && int.TryParse(remaining.FirstOrDefault(), out int r))
                LastQuotaUsage.RequestsRemaining = r;

            if (response.Headers.TryGetValues("x-ratelimit-limit", out var limit) && int.TryParse(limit.FirstOrDefault(), out int l))
            {
                 // We can derive "used" if needed, or store limit
                 // QuotaInfo structure might need genericizing or reuse RequestsLast as Limit
                 LastQuotaUsage.RequestsLast = l; // Abusing this field for Limit for now to match OddsService model reuse or add new prop
            }
        }
    }
}
