using Microsoft.EntityFrameworkCore;
using SportsBettingAnalyzer.Data;
using SportsBettingAnalyzer.Models;

namespace SportsBettingAnalyzer.Services
{
    public class HistoricalDataImportService
    {
        private readonly ApplicationDbContext _context;
        private readonly ILogger<HistoricalDataImportService> _logger;
        private readonly StatsScraperService _scraperService;

        public HistoricalDataImportService(
            ApplicationDbContext context,
            ILogger<HistoricalDataImportService> logger,
            StatsScraperService scraperService)
        {
            _context = context;
            _logger = logger;
            _scraperService = scraperService;
        }

        public async Task<int> ImportHistoricalGamesFromCSVAsync(string csvContent, string sport)
        {
            try
            {
                var lines = csvContent.Split('\n', StringSplitOptions.RemoveEmptyEntries);
                var imported = 0;

                // Skip header if present
                var startIndex = lines[0].Contains("Team1") || lines[0].Contains("team1") ? 1 : 0;

                for (int i = startIndex; i < lines.Length; i++)
                {
                    var line = lines[i].Trim();
                    if (string.IsNullOrWhiteSpace(line)) continue;

                    var parts = line.Split(',');
                    if (parts.Length < 4) continue;

                    try
                    {
                        var gameResult = new HistoricalGameResult
                        {
                            Sport = sport,
                            Team1 = parts[0].Trim().Trim('"'),
                            Team2 = parts[1].Trim().Trim('"'),
                            GameDate = DateTime.TryParse(parts[2].Trim().Trim('"'), out var date) ? date : DateTime.UtcNow,
                            Team1Score = int.TryParse(parts[3].Trim().Trim('"'), out var score1) ? score1 : null,
                            Team2Score = parts.Length > 4 && int.TryParse(parts[4].Trim().Trim('"'), out var score2) ? score2 : null
                        };

                        if (gameResult.Team1Score.HasValue && gameResult.Team2Score.HasValue)
                        {
                            gameResult.Team1Won = gameResult.Team1Score > gameResult.Team2Score;
                        }

                        // Check if already exists
                        var exists = await _context.HistoricalGameResults
                            .AnyAsync(g => g.Sport == gameResult.Sport &&
                                          g.Team1 == gameResult.Team1 &&
                                          g.Team2 == gameResult.Team2 &&
                                          g.GameDate.Date == gameResult.GameDate.Date);

                        if (!exists)
                        {
                            _context.HistoricalGameResults.Add(gameResult);
                            imported++;
                        }
                    }
                    catch (Exception ex)
                    {
                        _logger.LogWarning(ex, "Failed to parse line {Line}: {Content}", i, line);
                    }
                }

                await _context.SaveChangesAsync();
                _logger.LogInformation("Imported {Count} historical games for {Sport}", imported, sport);
                return imported;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error importing historical games");
                throw;
            }
        }

        public async Task<List<MLBetData>> ConvertHistoricalGamesToTrainingDataAsync(string sport)
        {
            try
            {
                var games = await _context.HistoricalGameResults
                    .Where(g => g.Sport == sport && 
                                g.Team1Score.HasValue && 
                                g.Team2Score.HasValue && 
                                g.Team1Won.HasValue)
                    .ToListAsync();

                var trainingData = new List<MLBetData>();

                foreach (var game in games)
                {
                    // Get team stats for this game
                    var team1Stats = await _context.TeamStats
                        .FirstOrDefaultAsync(t => t.TeamName == game.Team1 && t.Sport == sport);
                    
                    var team2Stats = await _context.TeamStats
                        .FirstOrDefaultAsync(t => t.TeamName == game.Team2 && t.Sport == sport);

                    // Create training data for moneyline bet on team1
                    // We'll use implied odds based on historical win rates
                    var team1WinRate = team1Stats?.WinRate ?? 0.5m;
                    var team2WinRate = team2Stats?.WinRate ?? 0.5m;
                    
                    // Calculate implied odds from win rates
                    var impliedOdds = team1WinRate > 0 ? (1m / team1WinRate - 1m) * 100m : 0m;
                    if (impliedOdds < 0) impliedOdds = -100m / (impliedOdds - 100m);

                    var betData = new MLBetData
                    {
                        Odds = (float)impliedOdds,
                        OddsFormat = 0f, // American
                        BetType = 0f, // Moneyline
                        Sport = GetSportNumeric(sport),
                        Spread = 0f,
                        OverUnder = 0f,
                        Team1WinRate = (float)(team1Stats?.WinRate ?? 0m),
                        Team2WinRate = (float)(team2Stats?.WinRate ?? 0m),
                        Team1AvgPointsFor = (float)(team1Stats?.AveragePointsFor ?? 0m),
                        Team2AvgPointsFor = (float)(team2Stats?.AveragePointsFor ?? 0m),
                        Team1AvgPointsAgainst = (float)(team1Stats?.AveragePointsAgainst ?? 0m),
                        Team2AvgPointsAgainst = (float)(team2Stats?.AveragePointsAgainst ?? 0m),
                        Label = game.Team1Won == true ? 1f : 0f
                    };

                    trainingData.Add(betData);
                }

                return trainingData;
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error converting historical games to training data");
                return new List<MLBetData>();
            }
        }

        private float GetSportNumeric(string sport)
        {
            return sport switch
            {
                "NFL" => 0f,
                "NBA" => 1f,
                "MLB" => 2f,
                "NHL" => 3f,
                "Soccer" => 4f,
                "NASCAR" => 5f,
                _ => 0f
            };
        }
    }
}

