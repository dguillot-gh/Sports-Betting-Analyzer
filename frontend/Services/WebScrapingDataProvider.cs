using AngleSharp;
using AngleSharp.Html.Dom;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    /// <summary>
    /// Web scraping provider for historical sports data
    /// Scrapes from public sports statistics websites
    /// IMPORTANT: Always respect robots.txt and terms of service
    /// </summary>
    public class WebScrapingDataProvider : IExternalDataProvider
    {
      private readonly IBrowsingContext _browsingContext;
    private readonly ILogger<WebScrapingDataProvider> _logger;
   private readonly HttpClient _httpClient;
        private int _requestCount = 0;
        private DateTime _lastRequestTime = DateTime.MinValue;

        // Rate limiting: max requests per minute to avoid blocking
   private const int MaxRequestsPerMinute = 10;

    public string ProviderName => "WebScraping";

        public WebScrapingDataProvider(ILogger<WebScrapingDataProvider> logger, HttpClient httpClient)
  {
          _logger = logger;
 _httpClient = httpClient;
            var config = Configuration.Default.WithDefaultLoader();
       _browsingContext = BrowsingContext.New(config);
        }

        public async Task<List<HistoricalGameResult>> GetHistoricalGamesAsync(
         string sport,
       DateTime? startDate = null,
            DateTime? endDate = null)
        {
 try
  {
                _logger.LogInformation("Scraping historical games for {Sport}", sport);

           var games = new List<HistoricalGameResult>();

    // Example: Scrape from Pro Football Reference (NFL)
     if (sport.Equals("NFL", StringComparison.OrdinalIgnoreCase))
       {
   games = await ScrapeNFLGamesAsync(startDate, endDate);
    }
     else if (sport.Equals("NBA", StringComparison.OrdinalIgnoreCase))
      {
   games = await ScrapeNBAGamesAsync(startDate, endDate);
      }
     else if (sport.Equals("NASCAR", StringComparison.OrdinalIgnoreCase))
      {
   games = await ScrapeNASCARGamesAsync(startDate, endDate);
      }

          _logger.LogInformation("Scraped {Count} games for {Sport}", games.Count, sport);
         return games;
      }
     catch (Exception ex)
  {
         _logger.LogError(ex, "Error scraping historical games for {Sport}", sport);
  return new List<HistoricalGameResult>();
   }
  }

        public async Task<List<LiveGameData>> GetLiveGamesAsync(string sport)
        {
            try
          {
         _logger.LogInformation("Scraping live games for {Sport}", sport);

  var games = new List<LiveGameData>();

 // Scrape current week/day games
  // Example: Get from ESPN scores page
          games = await ScrapeLiveGamesAsync(sport);

         return games;
      }
    catch (Exception ex)
   {
         _logger.LogError(ex, "Error scraping live games");
                return new List<LiveGameData>();
    }
        }

        public async Task<TeamStats?> GetTeamStatsAsync(string teamName, string sport)
  {
            try
       {
       _logger.LogInformation("Scraping team stats for {Team} in {Sport}", teamName, sport);

        // Apply rate limiting
      await ApplyRateLimitingAsync();

             // Example implementation
     var stats = new TeamStats { TeamName = teamName, Sport = sport };

        // Scrape from appropriate website based on sport
         // This would involve:
          // 1. Building a search URL
     // 2. Fetching the page with AngleSharp
          // 3. Parsing HTML selectors to extract stats
    // 4. Returning the stats

    return stats;
            }
     catch (Exception ex)
       {
       _logger.LogError(ex, "Error scraping team stats");
    return null;
            }
        }

        public async Task<PlayerStats?> GetPlayerStatsAsync(string playerName, string sport)
      {
            try
{
       _logger.LogInformation("Scraping player stats for {Player} in {Sport}", playerName, sport);

          await ApplyRateLimitingAsync();

        var stats = new PlayerStats { PlayerName = playerName, Sport = sport };

        // Similar to team stats, scrape from appropriate website

             return stats;
         }
      catch (Exception ex)
         {
    _logger.LogError(ex, "Error scraping player stats");
     return null;
            }
        }

   public async Task<bool> ValidateConnectionAsync()
   {
      try
    {
                _logger.LogInformation("Validating web scraping connection");

    // Test by trying to fetch a simple page
 var response = await _httpClient.GetAsync("https://www.pro-football-reference.com/");
         return response.IsSuccessStatusCode;
     }
    catch (Exception ex)
            {
        _logger.LogError(ex, "Error validating connection");
     return false;
 }
        }

 // PRIVATE HELPER METHODS

    private async Task<List<HistoricalGameResult>> ScrapeNFLGamesAsync(DateTime? startDate, DateTime? endDate)
      {
         var games = new List<HistoricalGameResult>();
         var targetYear = startDate?.Year ?? DateTime.Now.Year;

            try
            {
            await ApplyRateLimitingAsync();

                // Pro Football Reference - Get games from specific year
       var url = $"https://www.pro-football-reference.com/years/{targetYear}/games.htm";

      _logger.LogInformation("=== STARTING NFL SCRAPE ===");
      _logger.LogInformation("Fetching NFL games from {Url}", url);
      _logger.LogInformation("Date range: {StartDate} to {EndDate}", startDate, endDate);

         var document = await _browsingContext.OpenAsync(url);

      _logger.LogInformation("Document loaded. Status: {Status}", document.StatusCode);
      _logger.LogInformation("Document URL: {Url}", document.Url);

           // Pro Football Reference uses table with id "games"
      var gameRows = document.QuerySelectorAll("table#games tbody tr:not(.thead)");

      _logger.LogInformation("Found {Count} potential game rows", gameRows.Length);

      // Log the first few rows for debugging
      if (gameRows.Length == 0)
      {
          _logger.LogWarning("No game rows found! Checking for table...");
          var tables = document.QuerySelectorAll("table");
          _logger.LogInformation("Found {Count} tables total", tables.Length);
          foreach (var table in tables.Take(3))
          {
              var id = table.GetAttribute("id");
              var className = table.GetAttribute("class");
              _logger.LogInformation("Table found - ID: {Id}, Class: {Class}", id ?? "none", className ?? "none");
          }
      }

           foreach (var row in gameRows)
 {
       try
      {
                    // Skip header rows and rows without data
                    var weekCell = row.QuerySelector("th[data-stat='week_num']");
                    if (weekCell == null || string.IsNullOrWhiteSpace(weekCell.TextContent))
                        continue;

        var game = ParseNFLGameRow(row, targetYear);
               if (game != null)
 {
      games.Add(game);
                        _logger.LogDebug("Parsed game: {Team1} vs {Team2}", game.Team1, game.Team2);
        }
          }
        catch (Exception ex)
      {
        _logger.LogWarning(ex, "Error parsing NFL game row");
                }
        }

            _logger.LogInformation("Successfully parsed {Count} NFL games", games.Count);
            return games;
     }
            catch (Exception ex)
   {
        _logger.LogError(ex, "Error scraping NFL games");
                return games;
}
        }

        private async Task<List<HistoricalGameResult>> ScrapeNBAGamesAsync(DateTime? startDate, DateTime? endDate)
        {
  var games = new List<HistoricalGameResult>();
  var targetYear = (startDate?.Year ?? DateTime.Now.Year);

    try
   {
       await ApplyRateLimitingAsync();

                // Basketball Reference uses the season ending year
                // E.g., 2024-2025 season = 2025
    var year = targetYear + 1;
                var url = $"https://www.basketball-reference.com/leagues/NBA_{year}_games.html";

         _logger.LogInformation("Fetching NBA games from {Url}", url);

         var document = await _browsingContext.OpenAsync(url);

                // Basketball Reference has multiple tables for different months
                // Get all schedule tables
        var gameRows = document.QuerySelectorAll("table.suppress_all tbody tr:not(.thead)");

                _logger.LogInformation("Found {Count} potential NBA game rows", gameRows.Length);

                foreach (var row in gameRows)
  {
   try
         {
                        // Skip header/separator rows
                        var dateCell = row.QuerySelector("th[data-stat='date_game']");
                        if (dateCell == null || string.IsNullOrWhiteSpace(dateCell.TextContent))
                            continue;

 var game = ParseNBAGameRow(row);
       if (game != null)
   {
         games.Add(game);
                            _logger.LogDebug("Parsed NBA game: {Team1} vs {Team2}", game.Team1, game.Team2);
            }
 }
         catch (Exception ex)
 {
             _logger.LogWarning(ex, "Error parsing NBA game row");
              }
         }

                _logger.LogInformation("Successfully parsed {Count} NBA games", games.Count);
       return games;
          }
            catch (Exception ex)
            {
       _logger.LogError(ex, "Error scraping NBA games");
       return games;
  }
        }

     private async Task<List<LiveGameData>> ScrapeLiveGamesAsync(string sport)
        {
       var games = new List<LiveGameData>();

            try
            {
    await ApplyRateLimitingAsync();

      var url = $"https://www.espn.com/{(sport.ToLower())}";

          _logger.LogInformation("Fetching live games from {Url}", url);

          var document = await _browsingContext.OpenAsync(url);

    // Parse live games - structure varies by sport
              // This is a simplified example

  return games;
          }
        catch (Exception ex)
     {
       _logger.LogError(ex, "Error scraping live games");
           return games;
          }
 }

   private HistoricalGameResult? ParseNFLGameRow(AngleSharp.Dom.IElement row, int year)
        {
            try
      {
                // Pro Football Reference structure:
                // th[data-stat='week_num'] - Week number
                // td[data-stat='game_day_of_week'] - Day
                // td[data-stat='game_date'] - Date
                // td[data-stat='winner'] - Winning team (or blank if tie)
                // td[data-stat='game_location'] - @ if away, blank if home
                // td[data-stat='loser'] - Losing team (or blank if tie)
                // td[data-stat='pts_win'] - Winner points
                // td[data-stat='pts_lose'] - Loser points

                var dateCell = row.QuerySelector("td[data-stat='game_date']");
                var winnerCell = row.QuerySelector("td[data-stat='winner']");
                var loserCell = row.QuerySelector("td[data-stat='loser']");
                var ptsWinCell = row.QuerySelector("td[data-stat='pts_win']");
                var ptsLoseCell = row.QuerySelector("td[data-stat='pts_lose']");
                var locationCell = row.QuerySelector("td[data-stat='game_location']");

                if (dateCell == null || winnerCell == null || loserCell == null)
                    return null;

                var dateText = dateCell.TextContent.Trim();
                if (!DateTime.TryParse($"{dateText}, {year}", out var gameDate))
                {
                    // Try previous year if parsing fails (for early season games from previous year)
                    DateTime.TryParse($"{dateText}, {year - 1}", out gameDate);
                }

                var winnerTeam = winnerCell.TextContent.Trim();
                var loserTeam = loserCell.TextContent.Trim();

                if (string.IsNullOrEmpty(winnerTeam) || string.IsNullOrEmpty(loserTeam))
                    return null;

                var isHomeGame = string.IsNullOrEmpty(locationCell?.TextContent.Trim());

                // Determine Team1 (home) and Team2 (away)
                string team1, team2;
                int? team1Score = null, team2Score = null;

                if (isHomeGame)
                {
                    // Winner played at home
                    team1 = winnerTeam;
                    team2 = loserTeam;
                    if (int.TryParse(ptsWinCell?.TextContent.Trim(), out var pts1))
                        team1Score = pts1;
                    if (int.TryParse(ptsLoseCell?.TextContent.Trim(), out var pts2))
                        team2Score = pts2;
                }
                else
                {
                    // Winner played away (loser was home)
                    team1 = loserTeam;
                    team2 = winnerTeam;
                    if (int.TryParse(ptsLoseCell?.TextContent.Trim(), out var pts1))
                        team1Score = pts1;
                    if (int.TryParse(ptsWinCell?.TextContent.Trim(), out var pts2))
                        team2Score = pts2;
                }

       return new HistoricalGameResult
    {
       Sport = "NFL",
                    GameDate = gameDate,
                    Team1 = team1,
                    Team2 = team2,
                    Team1Score = team1Score,
                    Team2Score = team2Score,
                    Team1Won = team1Score.HasValue && team2Score.HasValue ? team1Score > team2Score : null
            };
 }
            catch (Exception ex)
      {
         _logger.LogWarning(ex, "Error parsing NFL game row");
     return null;
         }
 }

        private HistoricalGameResult? ParseNBAGameRow(AngleSharp.Dom.IElement row)
        {
      try
    {
                // Basketball Reference structure:
                // th[data-stat='date_game'] - Date
                // td[data-stat='visitor_team_name'] - Away team
                // td[data-stat='visitor_pts'] - Away team score
                // td[data-stat='home_team_name'] - Home team
                // td[data-stat='home_pts'] - Home team score

                var dateCell = row.QuerySelector("th[data-stat='date_game']");
                var awayTeamCell = row.QuerySelector("td[data-stat='visitor_team_name']");
                var awayPtsCell = row.QuerySelector("td[data-stat='visitor_pts']");
                var homeTeamCell = row.QuerySelector("td[data-stat='home_team_name']");
                var homePtsCell = row.QuerySelector("td[data-stat='home_pts']");

                if (dateCell == null || awayTeamCell == null || homeTeamCell == null)
                    return null;

                var dateText = dateCell.TextContent.Trim();
                if (!DateTime.TryParse(dateText, out var gameDate))
                    return null;

                var homeTeam = homeTeamCell.TextContent.Trim();
                var awayTeam = awayTeamCell.TextContent.Trim();

                if (string.IsNullOrEmpty(homeTeam) || string.IsNullOrEmpty(awayTeam))
                    return null;

                int? homeScore = null, awayScore = null;

                // Parse scores if available (games may not have been played yet)
                if (int.TryParse(homePtsCell?.TextContent.Trim(), out var hPts))
                    homeScore = hPts;
                if (int.TryParse(awayPtsCell?.TextContent.Trim(), out var aPts))
                    awayScore = aPts;

   return new HistoricalGameResult
      {
  Sport = "NBA",
                    GameDate = gameDate,
                    Team1 = homeTeam,
                    Team2 = awayTeam,
                    Team1Score = homeScore,
                    Team2Score = awayScore,
                    Team1Won = homeScore.HasValue && awayScore.HasValue ? homeScore > awayScore : null
    };
 }
            catch (Exception ex)
        {
      _logger.LogWarning(ex, "Error parsing NBA game row");
            return null;
        }
        }

        private async Task<List<HistoricalGameResult>> ScrapeNASCARGamesAsync(DateTime? startDate, DateTime? endDate)
        {
            var games = new List<HistoricalGameResult>();

            try
            {
                await ApplyRateLimitingAsync();

                // Racing Reference - NASCAR results
                var year = startDate?.Year ?? DateTime.Now.Year;
                var url = $"https://www.racing-reference.info/season-stats/{year}/W/";

                _logger.LogInformation("=== STARTING NASCAR SCRAPE ===");
                _logger.LogInformation("Fetching NASCAR races from {Url}", url);

                var document = await _browsingContext.OpenAsync(url);

                _logger.LogInformation("Document loaded. Status: {Status}", document.StatusCode);

                // Racing Reference uses different structure - look for race results table
                var raceRows = document.QuerySelectorAll("table.tb tr");

                _logger.LogInformation("Found {Count} potential race rows", raceRows.Length);

                foreach (var row in raceRows)
                {
                    try
                    {
                        var cells = row.QuerySelectorAll("td");
                        if (cells.Length < 3) continue;

                        // For NASCAR, we'll track race winners vs field
                        // Format: Race Name, Date, Winner
                        var dateCell = cells[0]?.TextContent.Trim();
                        var raceNameCell = cells[1]?.TextContent.Trim();
                        var winnerCell = cells[2]?.TextContent.Trim();

                        if (string.IsNullOrEmpty(dateCell) || string.IsNullOrEmpty(winnerCell))
                            continue;

                        if (DateTime.TryParse(dateCell, out var raceDate))
                        {
                            games.Add(new HistoricalGameResult
                            {
                                Sport = "NASCAR",
                                GameDate = raceDate,
                                Team1 = winnerCell, // Winner
                                Team2 = "Field", // Rest of field
                                Team1Score = 1, // Winner
                                Team2Score = 0, // Field
                                Team1Won = true
                            });

                            _logger.LogDebug("Parsed NASCAR race: {Winner} on {Date}", winnerCell, raceDate);
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Error parsing NASCAR race row");
                    }
                }

                _logger.LogInformation("Successfully parsed {Count} NASCAR races", games.Count);
                return games;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error scraping NASCAR races");
                return games;
            }
        }

        private async Task ApplyRateLimitingAsync()
        {
  var now = DateTime.UtcNow;
         var timeSinceLastRequest = (now - _lastRequestTime).TotalSeconds;

            // Reset counter if more than a minute has passed
  if (timeSinceLastRequest > 60)
  {
          _requestCount = 0;
            }

if (_requestCount >= MaxRequestsPerMinute)
       {
      var delayTime = (int)(60 - timeSinceLastRequest);
           _logger.LogInformation("Rate limit reached. Delaying for {DelayTime} seconds", delayTime);
       await Task.Delay(delayTime * 1000);
                _requestCount = 0;
        }

     _requestCount++;
            _lastRequestTime = now;
        }
    }
}
